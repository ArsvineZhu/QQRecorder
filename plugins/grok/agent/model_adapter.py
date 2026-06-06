from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field

from ..context.evidence import AgentToolCall
from .llm_chain_logger import log_llm_chain, usage_from_response
from .prompt import build_model_messages, render_working_context

logger = logging.getLogger("grok.model")


@dataclass
class AgentTurnResult:
    text: str
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    model_name: str = ""
    request_summary: str = ""
    response_summary: str = ""
    raw_assistant_message: dict | None = None
    messages: list[dict] | None = None


async def run_agent_turn(
    *,
    api,
    working_context,
    settings,
    registry,
    messages: list[dict] | None = None,
) -> AgentTurnResult:
    tool_defs = registry.list_for_model()
    working_context_text = render_working_context(working_context)
    if messages is None:
        messages = build_model_messages(working_context, settings)
    else:
        # Update budget info in the existing history for the next turn
        _update_budget_in_user_message(messages, working_context)
    kwargs = {
        "model": settings.model.model or None,
        "temperature": settings.model.temperature,
        "max_tokens": settings.model.max_tokens_group
        if working_context.context.chat_type == "group"
        else settings.model.max_tokens_private,
        "timeout_sec": settings.model.timeout_sec,
    }

    thinking_config = _build_thinking_kwargs(settings.model)
    kwargs.update(thinking_config)

    if tool_defs:
        try:
            response = await _call_chat(
                api,
                messages,
                kwargs=kwargs,
                tools=tool_defs,
            )
        except TypeError:
            response = await _call_chat(
                api,
                messages,
                kwargs=kwargs,
                functions=[item["function"] for item in tool_defs],
            )
    else:
        response = await _call_chat(api, messages, kwargs=kwargs)

    tool_calls = _extract_tool_calls(response)
    text = _extract_text(response).strip()
    raw_msg = _extract_raw_assistant_message(response)

    if tool_calls:
        tools_log = "; ".join(f"{c.name}({c.arguments})" for c in tool_calls)
        logger.info("model: tool calls %s", tools_log)
    elif not text:
        # Debug: log full response structure when content is empty
        choices = getattr(response, "choices", None) or []
        if choices:
            msg = getattr(choices[0], "message", None)
            logger.info(
                "model: empty text — response choices[0].message "
                "content=%s reasoning_content=%s tool_calls=%s finish_reason=%s",
                repr(getattr(msg, "content", "MISSING")),
                repr(getattr(msg, "reasoning_content", "MISSING")),
                repr(getattr(msg, "tool_calls", "MISSING")),
                repr(getattr(choices[0], "finish_reason", "MISSING")),
            )
        else:
            logger.info(
                "model: empty text — response type=%s has_choices=%s raw=%s",
                type(response).__name__,
                bool(choices),
                str(type(response)),
            )
    else:
        logger.info("model: text response len=%d text=%s", len(text), text[:120])

    request_id = str(
        getattr(working_context, "llm_request_id", "") or uuid.uuid4().hex[:12]
    )
    step = int(getattr(working_context, "llm_step", 1) or 1)
    source_message_id = str(getattr(working_context, "source_message_id", "") or "")
    if settings.trace.log_llm_chain:
        log_llm_chain(
            request_id=request_id,
            chat_type=str(getattr(working_context.context, "chat_type", "") or ""),
            chat_id=str(getattr(working_context.context, "chat_id", "") or ""),
            source_message_id=source_message_id,
            step=step,
            messages=messages,
            response_text=text,
            tool_calls=tool_calls,
            usage=usage_from_response(response),
        )

    response_summary = text or (
        "; ".join(call.name for call in tool_calls) if tool_calls else ""
    )
    return AgentTurnResult(
        text=text,
        tool_calls=tool_calls,
        model_name=str(getattr(response, "model", None) or settings.model.model or ""),
        request_summary=_summarize(working_context_text, settings.trace.preview_chars),
        response_summary=_summarize(response_summary, settings.trace.preview_chars),
        raw_assistant_message=raw_msg,
        messages=messages,
    )


async def _call_chat(api, messages, *, kwargs: dict, **extra):
    timeout_sec = float(kwargs.pop("timeout_sec", 30) or 30)
    async with asyncio.timeout(timeout_sec):
        response = await api.ai.chat(messages, **kwargs, **extra)
    logger.debug("model: _call_chat response type=%s", type(response).__name__)
    return response


def _extract_tool_calls(response) -> list[AgentToolCall]:
    calls: list[AgentToolCall] = []
    for tool_call in _iter_tool_calls(response):
        function = _get_nested(tool_call, ("function",))
        if function is None:
            continue
        name = str(_get_nested(function, ("name",)) or "").strip()
        if not name:
            continue
        arguments = _get_nested(function, ("arguments",))
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments)
            except json.JSONDecodeError:
                logger.warning(
                    "model: skipped malformed tool call arguments tool=%s raw=%s",
                    name,
                    arguments[:1000],
                )
                continue
        else:
            payload = arguments or {}
        if not isinstance(payload, dict):
            payload = {}
        tool_call_id = str(getattr(tool_call, "id", "") or "")
        calls.append(
            AgentToolCall(name=name, arguments=payload, tool_call_id=tool_call_id)
        )
    return calls


def _extract_text(response) -> str:
    if isinstance(response, str):
        return response
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if content:  # truthy — not None and not ""
                return str(content)
            # content is None or "" — e.g. thinking mode, finish_reason="length"
            # Don't return reasoning_content (internal thinking), let caller handle
        if getattr(choices[0], "text", None):
            return str(choices[0].text)
    if getattr(response, "content", None):
        return str(response.content)
    return ""


def _extract_raw_assistant_message(response) -> dict | None:
    """Extract the raw assistant message dict from a non-streaming response.

    Returns a dict with keys like role, content, reasoning_content, tool_calls
    suitable for appending to the messages list per DeepSeek docs.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    if message is None:
        return None
    result: dict = {"role": "assistant"}
    content = getattr(message, "content", None)
    if content is not None:
        result["content"] = content
    rc = getattr(message, "reasoning_content", None)
    if rc is not None:
        result["reasoning_content"] = rc
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls is not None:
        result["tool_calls"] = [_serialize_tool_call(tc) for tc in tool_calls]
    return result


def _serialize_tool_call(tc) -> dict:
    """Serialize a tool call object to a dict suitable for API re-submission."""
    if hasattr(tc, "model_dump"):
        return tc.model_dump()
    base: dict[str, object] = {
        "id": str(getattr(tc, "id", "") or ""),
        "type": "function",
    }
    func = getattr(tc, "function", None) or {}
    base["function"] = {
        "name": str(getattr(func, "name", "") or ""),
        "arguments": str(getattr(func, "arguments", "") or ""),
    }
    return base


def _iter_tool_calls(response):
    direct = _get_nested(response, ("tool_calls",))
    if direct:
        yield from direct
    choices = _get_nested(response, ("choices",)) or []
    for choice in choices:
        message = _get_nested(choice, ("message",))
        calls = _get_nested(message, ("tool_calls",)) or []
        yield from calls
        function_call = _get_nested(message, ("function_call",))
        if function_call is not None:
            yield {"function": function_call}
    function_call = _get_nested(response, ("function_call",))
    if function_call is not None:
        yield {"function": function_call}


def _get_nested(obj, path: tuple[str, ...]):
    current = obj
    for part in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _summarize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _build_thinking_kwargs(model_cfg) -> dict:
    if not model_cfg.thinking_enabled:
        return {}
    effort = str(getattr(model_cfg, "thinking_effort", "high") or "high")
    return {
        "reasoning_effort": effort,
        "extra_body": {"thinking": {"type": "enabled"}},
    }


def _update_budget_in_user_message(
    messages: list[dict],
    working_context,
) -> None:
    """Update tool_call_budget_remaining in the last user message."""
    remaining = int(getattr(working_context, "tool_call_budget_remaining", 0) or 0)
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                import re

                msg["content"] = re.sub(
                    r"当前剩余额度：`\d+`",
                    f"当前剩余额度：`{remaining}`",
                    content,
                )
            break
