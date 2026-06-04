from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import is_dataclass
from typing import Any

from ..agent.model_adapter import run_agent_turn
from ..context.evidence import (
    AgentOutcome,
    AgentStep,
    AgentWorkingContext,
    ContextBundle,
    EvidenceBlock,
)
from ..tools.context_tools import build_context_tools
from ..tools.media_tools import build_media_tools
from ..tools.profile_tools import (
    build_create_profile_tool,
    build_delete_profile_tool,
    build_load_profile_tool,
    build_update_profile_tool,
)
from ..tools.registry import ToolRegistry, ToolResponse

logger = logging.getLogger("grok.runtime")


class AgentRuntime:
    def __init__(
        self,
        plugin,
        *,
        registry: Any | None = None,
        model_runner: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.plugin = plugin
        self.registry = registry or self._build_registry(plugin)
        self._model_runner = model_runner or self._run_model

    async def run(self, *, event, source_msg, trigger_reason: str) -> AgentOutcome:
        working_context = AgentWorkingContext(
            context=ContextBundle(
                chat_type=str(
                    getattr(source_msg, "chat_type", "") or _chat_type(event)
                ),
                chat_id=str(
                    getattr(source_msg, "group_id", None)
                    or getattr(event, "group_id", None)
                    or getattr(source_msg, "user_id", "")
                    or getattr(event, "user_id", "")
                ),
                user_id=str(
                    getattr(source_msg, "user_id", "") or getattr(event, "user_id", "")
                ),
                current_message=str(
                    getattr(event, "raw_message", "")
                    or getattr(source_msg, "raw_message", "")
                    or ""
                ),
                trigger_reason=trigger_reason,
                bot_id=str(
                    getattr(event, "self_id", "")
                    or getattr(source_msg, "self_id", "")
                    or ""
                ),
                current_sender=str(
                    getattr(source_msg, "sender_card", "")
                    or getattr(source_msg, "sender_nickname", "")
                    or getattr(event, "user_id", "")
                    or ""
                ),
                current_time=str(
                    getattr(source_msg, "timestamp", "")
                    or getattr(event, "time", "")
                    or ""
                ),
                group_instruction=str(
                    getattr(source_msg, "chat_type", "") or _chat_type(event)
                ),
                parser_version="qq_recorder:v1",
                context_version="grok_context:v1",
                profile_version="grok_profile:v1",
            ),
            evidence=[],
            step_budget=int(getattr(self.plugin.settings.agent, "max_steps", 4) or 4),
        )
        steps: list[AgentStep] = []
        total_tool_calls = 0
        max_tool_calls_total = _tool_call_total_budget(self.plugin.settings.agent)
        seen_track_reply_keys: set[tuple[str, int]] = set()

        for _ in range(working_context.step_budget):
            turn = await self._model_runner(
                working_context=working_context,
                settings=self.plugin.settings,
                registry=self.registry,
                api=self.plugin.api,
            )
            if not turn.tool_calls:
                text = turn.text.strip()
                if not text:
                    text = "暂时没有足够的信息来回答你"
                    logger.info("runtime: empty model response, using fallback")
                return AgentOutcome(
                    text=text,
                    working_context=working_context,
                    steps=steps,
                    model_name=turn.model_name,
                    error_code=None,
                )

            for tool_call in turn.tool_calls[
                : self.plugin.settings.agent.max_tool_calls_per_turn
            ]:
                step = AgentStep(
                    kind="tool",
                    tool_name=tool_call.name,
                    status="pending",
                    summary="",
                )
                if total_tool_calls >= max_tool_calls_total:
                    budget_response = ToolResponse(
                        status="failed",
                        data={},
                        error_code="tool_budget_exceeded",
                        message=(
                            "本次 Agent 运行的工具调用次数已达到上限，停止继续调用工具"
                        ),
                        retryable=False,
                    )
                    step.status = "skipped"
                    step.summary = _normalize_result_payload(budget_response)
                    steps.append(step)
                    working_context.evidence.append(
                        EvidenceBlock(
                            kind="tool_result",
                            label="runtime",
                            content=step.summary,
                            source="runtime",
                            metadata={"arguments": tool_call.arguments},
                        )
                    )
                    logger.info(
                        "runtime: global tool budget exceeded budget=%d tool=%s",
                        max_tool_calls_total,
                        tool_call.name,
                    )
                    return AgentOutcome(
                        text="这条消息的上下文工具查询次数已经达到上限，我先不继续查了",
                        working_context=working_context,
                        steps=steps,
                        model_name=getattr(turn, "model_name", "") or "",
                        error_code="tool_budget_exceeded",
                    )

                duplicate_response = _check_duplicate_track_reply(
                    tool_call=tool_call,
                    source_msg=source_msg,
                    seen_track_reply_keys=seen_track_reply_keys,
                )
                if duplicate_response is not None:
                    total_tool_calls += 1
                    step.status = "skipped"
                    step.summary = _normalize_result_payload(duplicate_response)
                    steps.append(step)
                    working_context.evidence.append(
                        EvidenceBlock(
                            kind="tool_result",
                            label=tool_call.name,
                            content=step.summary,
                            source="runtime",
                            metadata={"arguments": tool_call.arguments},
                        )
                    )
                    logger.info(
                        "runtime: duplicate track_reply skipped args=%s",
                        tool_call.arguments,
                    )
                    return AgentOutcome(
                        text="我已经查过这条回复链，记录里没有更多可用结果；请补充原消息内容，或我先按当前消息判断。",
                        working_context=working_context,
                        steps=steps,
                        model_name=getattr(turn, "model_name", "") or "",
                        error_code="duplicate_track_reply",
                    )

                logger.info(
                    "runtime: execute tool=%s args=%s",
                    tool_call.name,
                    tool_call.arguments,
                )
                try:
                    total_tool_calls += 1
                    result = await self.registry.execute(
                        tool_call.name,
                        tool_call.arguments,
                        context={
                            "event": event,
                            "source_msg": source_msg,
                            "chat_type": working_context.context.chat_type,
                            "chat_id": working_context.context.chat_id,
                            "user_id": working_context.context.user_id,
                        },
                    )
                except Exception as exc:
                    step.status = "error"
                    step.summary = str(exc)
                    logger.info(
                        "runtime: tool error tool=%s error=%s", tool_call.name, exc
                    )
                    working_context.evidence.append(
                        EvidenceBlock(
                            kind="tool_error",
                            label=tool_call.name,
                            content=str(exc),
                            source="tool",
                        )
                    )
                else:
                    step.status = "ok"
                    rendered = _clip_text(
                        _normalize_result_payload(result),
                        getattr(
                            self.plugin.settings.agent,
                            "max_evidence_chars",
                            6000,
                        ),
                    )
                    step.summary = rendered
                    logger.info(
                        "runtime: tool ok tool=%s chars=%d",
                        tool_call.name,
                        len(rendered),
                    )
                    working_context.evidence.append(
                        EvidenceBlock(
                            kind="tool_result",
                            label=tool_call.name,
                            content=rendered,
                            source="tool",
                            metadata={"arguments": tool_call.arguments},
                        )
                    )
                steps.append(step)

        return AgentOutcome(
            text="很抱歉，请告诉 Arsvine 我的 AI 出问题了",
            working_context=working_context,
            steps=steps,
            model_name="",
            error_code="max_steps_exceeded",
        )

    async def _run_model(self, *, working_context, settings, registry, api):
        return await run_agent_turn(
            api=api,
            working_context=working_context,
            settings=settings,
            registry=registry,
        )

    @staticmethod
    def _build_registry(plugin) -> ToolRegistry:
        registry = ToolRegistry()
        for tool in build_context_tools(plugin):
            registry.register(tool)
        for tool in build_media_tools(plugin):
            registry.register(tool)
        registry.register(build_load_profile_tool(plugin))
        registry.register(build_create_profile_tool(plugin))
        registry.register(build_update_profile_tool(plugin))
        registry.register(build_delete_profile_tool(plugin))
        return registry


def _tool_call_total_budget(agent_settings: Any) -> int:
    configured = getattr(agent_settings, "max_tool_calls_total", None)
    if configured is not None:
        return max(1, int(configured))
    max_steps = max(1, int(getattr(agent_settings, "max_steps", 4) or 4))
    per_turn = max(1, int(getattr(agent_settings, "max_tool_calls_per_turn", 3) or 3))
    return max_steps * per_turn


def _check_duplicate_track_reply(
    *,
    tool_call: Any,
    source_msg: Any,
    seen_track_reply_keys: set[tuple[str, int]],
) -> ToolResponse | None:
    if getattr(tool_call, "name", "") != "track_reply":
        return None

    arguments = getattr(tool_call, "arguments", {}) or {}
    key = _track_reply_key(arguments, source_msg)
    if key not in seen_track_reply_keys:
        seen_track_reply_keys.add(key)
        return None

    return ToolResponse(
        status="failed",
        data={},
        error_code="duplicate_track_reply",
        message="同一条引用链已经查询过，不要再次调用 track_reply",
        retryable=False,
    )


def _track_reply_key(arguments: dict[str, Any], source_msg: Any) -> tuple[str, int]:
    message_id = str(
        arguments.get("message_id")
        or getattr(source_msg, "message_id", "")
        or getattr(source_msg, "id", "")
        or "current"
    )
    return (message_id, _safe_track_reply_depth(arguments.get("max_depth")))


def _safe_track_reply_depth(value: Any) -> int:
    try:
        depth = int(value or 6)
    except (TypeError, ValueError):
        return 6
    return max(1, depth)


def _chat_type(event) -> str:
    return "group" if getattr(event, "group_id", None) is not None else "private"


def _normalize_result_payload(result: Any) -> str:
    if isinstance(result, ToolResponse):
        return json.dumps(
            {
                "status": result.status,
                "data": result.data,
                "message": result.message,
                "error_code": result.error_code,
                "retryable": result.retryable,
                "meta": result.meta,
            },
            ensure_ascii=False,
        )
    if is_dataclass(result) and not isinstance(result, type):
        payload = getattr(result, "__dict__", str(result))
        return json.dumps(payload, ensure_ascii=False)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"
