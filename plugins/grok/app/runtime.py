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
from ..tools.guide_tools import build_load_tool_guide_tool
from ..tools.media_tools import build_media_tools
from ..tools.profile_tools import (
    build_create_profile_tool,
    build_delete_profile_tool,
    build_load_profile_tool,
    build_update_profile_tool,
)
from ..tools.registry import ToolRegistry, ToolResponse
from ..tools.terminate_tools import build_terminate_tool

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
        self._messages_history: list[dict] | None = None

    async def run(self, *, event, source_msg, trigger_reason: str) -> AgentOutcome:  # noqa: C901
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
            tool_call_budget_total=_tool_call_total_budget(self.plugin.settings.agent),
            tool_call_budget_remaining=_tool_call_total_budget(
                self.plugin.settings.agent
            ),
        )
        steps: list[AgentStep] = []
        total_tool_calls = 0
        max_tool_calls_total = working_context.tool_call_budget_total
        seen_track_reply_keys: set[tuple[str, int]] = set()
        self._messages_history = None

        for _ in range(working_context.step_budget):
            turn = await self._model_runner(
                working_context=working_context,
                settings=self.plugin.settings,
                registry=self.registry,
                api=self.plugin.api,
            )

            # First call returns the initial messages; subsequent calls reuse history
            if self._messages_history is None:
                msgs = getattr(turn, "messages", None)
                if msgs is not None:
                    self._messages_history = msgs

            # Append assistant response to history (preserves content,
            # reasoning_content, tool_calls for DeepSeek thinking mode)
            raw_msg = getattr(turn, "raw_assistant_message", None)
            if raw_msg is not None and self._messages_history is not None:
                self._messages_history.append(raw_msg)

            if not turn.tool_calls:
                text = turn.text.strip()
                if not text:
                    text = "模型无回复，请告诉 Arsvine 我的 AI 出问题了"
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
                counts_against_budget = _counts_against_budget(tool_call.name)
                if counts_against_budget and total_tool_calls >= max_tool_calls_total:
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
                    if self._messages_history is not None:
                        self._messages_history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.tool_call_id,
                                "content": step.summary,
                            }
                        )
                    logger.info(
                        "runtime: global tool budget exceeded budget=%d tool=%s",
                        max_tool_calls_total,
                        tool_call.name,
                    )
                    # Don't return — skip the tool, let the model continue
                    # with the context it already has
                    continue

                duplicate_response = _check_duplicate_track_reply(
                    tool_call=tool_call,
                    source_msg=source_msg,
                    seen_track_reply_keys=seen_track_reply_keys,
                )
                if duplicate_response is not None:
                    step.status = "skipped"
                    step.summary = _normalize_result_payload(
                        duplicate_response,
                        limit=getattr(
                            self.plugin.settings.agent,
                            "max_evidence_chars",
                            6000,
                        ),
                        tool_name=tool_call.name,
                    )
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
                    if self._messages_history is not None:
                        self._messages_history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.tool_call_id,
                                "content": step.summary,
                            }
                        )
                    logger.info(
                        "runtime: duplicate track_reply skipped args=%s",
                        tool_call.arguments,
                    )
                    continue

                logger.info(
                    "runtime: execute tool=%s args=%s",
                    tool_call.name,
                    tool_call.arguments,
                )
                try:
                    if counts_against_budget:
                        total_tool_calls += 1
                        working_context.tool_call_budget_remaining = max(
                            0, max_tool_calls_total - total_tool_calls
                        )
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
                    rendered = _normalize_result_payload(
                        result,
                        limit=getattr(
                            self.plugin.settings.agent,
                            "max_evidence_chars",
                            6000,
                        ),
                        tool_name=tool_call.name,
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
                    if tool_call.name == "terminate":
                        step.summary = rendered
                        steps.append(step)
                        logger.info("runtime: terminate requested")
                        return AgentOutcome(
                            text="",
                            working_context=working_context,
                            steps=steps,
                            model_name=turn.model_name,
                            error_code="terminated_by_agent",
                            termination_reason=_termination_reason(
                                tool_call.arguments,
                                result,
                            ),
                        )
                steps.append(step)

                # Append tool result to self._messages_history for next API call
                if self._messages_history is not None:
                    self._messages_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.tool_call_id,
                            "content": step.summary,
                        }
                    )

        return AgentOutcome(
            text=(
                f"Agent 运行达到最大步数，{_assistant_name(self.plugin.settings)}."
                "exe 已停止运行"
            ),
            working_context=working_context,
            steps=steps,
            model_name="",
            error_code="max_steps_exceeded",
        )

    async def _run_model(
        self, *, working_context, settings, registry, api, messages=None
    ):
        return await run_agent_turn(
            api=api,
            working_context=working_context,
            settings=settings,
            registry=registry,
            messages=messages,
        )

    @staticmethod
    def _merge_history(
        messages_history: list[dict] | None,
    ) -> list[dict] | None:
        """Pass message history for the next API call, or None for the first turn."""
        return messages_history

    @staticmethod
    def _build_registry(plugin) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(build_load_tool_guide_tool(plugin))
        for tool in build_context_tools(plugin):
            registry.register(tool)
        for tool in build_media_tools(plugin):
            registry.register(tool)
        registry.register(build_terminate_tool(plugin))
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


def _counts_against_budget(tool_name: str) -> bool:
    return tool_name != "load_tool_guide"


def _assistant_name(settings: Any) -> str:
    prompt = getattr(settings, "prompt", None)
    return str(getattr(prompt, "assistant_name", "Grok") or "Grok").strip()


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


def _normalize_result_payload(
    result: Any,
    *,
    limit: int | None = None,
    tool_name: str = "",
) -> str:
    if isinstance(result, ToolResponse):
        payload = {
            "status": result.status,
            "data": result.data,
            "message": result.message,
            "error_code": result.error_code,
            "retryable": result.retryable,
            "meta": result.meta,
        }
        return _dump_payload(payload, limit=limit, tool_name=tool_name)
    if is_dataclass(result) and not isinstance(result, type):
        payload = getattr(result, "__dict__", str(result))
        return _dump_payload(payload, limit=limit, tool_name=tool_name)
    if isinstance(result, dict):
        return _dump_payload(result, limit=limit, tool_name=tool_name)
    text = str(result)
    if limit is None:
        return text
    return _clip_text(text, limit)


def _dump_payload(payload: Any, *, limit: int | None, tool_name: str) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    if limit is None or len(text) <= limit:
        return text
    if isinstance(payload, dict):
        structured = _shrink_structured_payload(
            payload, limit=limit, tool_name=tool_name
        )
        structured_text = json.dumps(structured, ensure_ascii=False)
        if len(structured_text) <= limit:
            return structured_text
        preview = _build_preview_payload(structured, limit)
        preview_text = json.dumps(preview, ensure_ascii=False)
        if len(preview_text) <= limit:
            return preview_text
        fallback = _build_minimal_fallback_payload(payload, text, limit)
        fallback_text = json.dumps(fallback, ensure_ascii=False)
        if len(fallback_text) <= limit:
            return fallback_text
        return json.dumps(
            _build_minimal_fallback_payload(payload, text, max(32, limit - 20)),
            ensure_ascii=False,
        )
    fallback = {
        "status": "ok",
        "data": {"preview": _clip_text(text, max(16, (limit or 120) - 40))},
    }
    fallback_text = json.dumps(fallback, ensure_ascii=False)
    if limit is None or len(fallback_text) <= limit:
        return fallback_text
    fallback["data"]["preview"] = _clip_text(
        text,
        max(
            8,
            (
                limit
                - len(
                    json.dumps(
                        {"status": "ok", "data": {"preview": ""}}, ensure_ascii=False
                    )
                )
            )
            - 2,
        ),
    )
    return json.dumps(fallback, ensure_ascii=False)


def _shrink_structured_payload(
    payload: dict[str, Any],
    *,
    limit: int,
    tool_name: str,
) -> dict[str, Any]:
    if tool_name in {"load_context", "track_reply"}:
        return _shrink_multi_message_payload(payload, limit=limit)
    if tool_name == "load_message":
        return _shrink_single_message_payload(payload, limit=limit)
    return payload


def _shrink_multi_message_payload(
    payload: dict[str, Any], *, limit: int
) -> dict[str, Any]:
    data = payload.get("data", {}) or {}
    messages = data.get("messages", []) or []
    if not isinstance(messages, list):
        return payload

    message_count = len(messages)
    for count in range(message_count, 0, -1):
        for raw_limit in (120, 80, 48, 24):
            clipped_messages = [
                _compact_message_payload(item, raw_limit=raw_limit, minimal=False)
                for item in messages[:count]
                if isinstance(item, dict)
            ]
            candidate = dict(payload)
            candidate_data = dict(data)
            candidate_data["messages"] = clipped_messages
            omitted = max(0, message_count - count)
            if omitted:
                candidate_data["omitted_message_count"] = omitted
            candidate["data"] = candidate_data
            if len(json.dumps(candidate, ensure_ascii=False)) <= limit:
                return candidate
        for raw_limit in (48, 24, 12):
            clipped_messages = [
                _compact_message_payload(item, raw_limit=raw_limit, minimal=True)
                for item in messages[:count]
                if isinstance(item, dict)
            ]
            candidate = dict(payload)
            candidate_data = dict(data)
            candidate_data["messages"] = clipped_messages
            omitted = max(0, message_count - count)
            if omitted:
                candidate_data["omitted_message_count"] = omitted
            candidate["data"] = candidate_data
            if len(json.dumps(candidate, ensure_ascii=False)) <= limit:
                return candidate
    return payload


def _shrink_single_message_payload(
    payload: dict[str, Any], *, limit: int
) -> dict[str, Any]:
    data = payload.get("data", {}) or {}
    message = data.get("message", {}) or {}
    if not isinstance(message, dict):
        return payload
    for raw_limit in (160, 100, 60, 32):
        candidate = dict(payload)
        candidate_data = dict(data)
        candidate_data["message"] = _compact_message_payload(
            message, raw_limit=raw_limit, minimal=False
        )
        candidate["data"] = candidate_data
        if len(json.dumps(candidate, ensure_ascii=False)) <= limit:
            return candidate
    for raw_limit in (48, 24, 12):
        candidate = dict(payload)
        candidate_data = dict(data)
        candidate_data["message"] = _compact_message_payload(
            message, raw_limit=raw_limit, minimal=True
        )
        candidate["data"] = candidate_data
        if len(json.dumps(candidate, ensure_ascii=False)) <= limit:
            return candidate
    return payload


def _pick_sender_label(message: dict[str, Any]) -> tuple[str, str] | None:
    sender_nickname = message.get("sender_nickname", "")
    sender_card = message.get("sender_card", "")
    nickname = message.get("nickname", "")
    user_id = message.get("user_id", "")
    if sender_nickname:
        return ("sender_nickname", sender_nickname)
    if sender_card:
        return ("sender_card", sender_card)
    if nickname:
        return ("nickname", nickname)
    if user_id:
        return ("user_id", user_id)
    return None


def _compact_message_payload(
    message: dict[str, Any],
    *,
    raw_limit: int,
    minimal: bool,
) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "message_id": message.get("message_id", ""),
        "timestamp": message.get("timestamp", ""),
        "raw_message": _clip_text(str(message.get("raw_message", "") or ""), raw_limit),
    }
    label = _pick_sender_label(message)
    if label:
        compact[label[0]] = label[1]

    has_image = bool(message.get("has_image", False))
    has_forward = bool(message.get("has_forward", False))
    if has_image:
        compact["has_image"] = True
    if has_forward:
        compact["has_forward"] = True

    if not minimal:
        user_id = message.get("user_id", "")
        sender_card = message.get("sender_card", "")
        nickname = message.get("nickname", "")
        if user_id and "user_id" not in compact:
            compact["user_id"] = user_id
        if sender_card and "sender_card" not in compact:
            compact["sender_card"] = sender_card
        if nickname and "nickname" not in compact:
            compact["nickname"] = nickname
    return compact


def _build_preview_payload(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    preview_source = json.dumps(payload.get("data", {}), ensure_ascii=False)
    allowed = max(16, limit - 120)
    return {
        "status": payload.get("status", "ok"),
        "data": {"preview": _clip_text(preview_source, allowed)},
        "message": payload.get("message", ""),
        "error_code": payload.get("error_code"),
        "retryable": payload.get("retryable", False),
        "meta": payload.get("meta", {}),
    }


def _build_minimal_fallback_payload(
    payload: dict[str, Any],
    text: str,
    limit: int,
) -> dict[str, Any]:
    base = {
        "status": payload.get("status", "ok"),
        "data": {"preview": ""},
        "message": payload.get("message", ""),
        "error_code": payload.get("error_code"),
        "retryable": payload.get("retryable", False),
    }
    overhead = len(json.dumps(base, ensure_ascii=False))
    allowed = max(8, limit - overhead - 2)
    base["data"]["preview"] = _clip_text(text, allowed)
    return base


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _termination_reason(arguments: dict[str, Any], result: Any) -> str | None:
    raw_reason = str(arguments.get("reason", "") or "").strip()
    if raw_reason:
        return raw_reason
    if isinstance(result, ToolResponse):
        data_reason = result.data.get("reason")
        return str(data_reason).strip() or None
    if isinstance(result, dict):
        data = result.get("data", {}) or {}
        if isinstance(data, dict):
            return str(data.get("reason", "") or "").strip() or None
    return None
