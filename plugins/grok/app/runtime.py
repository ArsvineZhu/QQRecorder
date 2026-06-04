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
from ..tools.registry import ToolRegistry

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
                logger.info(
                    "runtime: execute tool=%s args=%s",
                    tool_call.name,
                    tool_call.arguments,
                )
                try:
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


def _chat_type(event) -> str:
    return "group" if getattr(event, "group_id", None) is not None else "private"


def _normalize_result_payload(result: Any) -> str:
    if is_dataclass(result) and not isinstance(result, type):
        d = result.__dict__ if hasattr(result, "__dict__") else {}
        data = d.get("data") or {}
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False)
        payload = getattr(result, "__dict__", str(result))
    else:
        payload = result
    return str(payload)


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"
