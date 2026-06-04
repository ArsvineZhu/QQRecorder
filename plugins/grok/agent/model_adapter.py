from __future__ import annotations

import asyncio
import json
import logging
import pprint
from dataclasses import dataclass, field

from ..context.evidence import AgentToolCall
from .prompt import build_model_messages, render_working_context

logger = logging.getLogger("grok.model")


@dataclass
class AgentTurnResult:
    text: str
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    model_name: str = ""
    request_summary: str = ""
    response_summary: str = ""


async def run_agent_turn(
    *,
    api,
    working_context,
    settings,
    registry,
) -> AgentTurnResult:
    tool_defs = registry.list_for_model()
    working_context_text = render_working_context(working_context)
    messages = build_model_messages(working_context, settings)
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

    if tool_calls:
        tools_log = "; ".join(f"{c.name}({c.arguments})" for c in tool_calls)
        logger.info("model: tool calls %s", tools_log)
    else:
        logger.info("model: text response len=%d text=%s", len(text), text[:120])

    # Log LLM chain if enabled (skip system prompt, skip reasoning_content)
    _log_llm_chain(working_context, messages, tool_calls, text, settings)

    response_summary = text or (
        "; ".join(call.name for call in tool_calls) if tool_calls else ""
    )
    return AgentTurnResult(
        text=text,
        tool_calls=tool_calls,
        model_name=str(getattr(response, "model", None) or settings.model.model or ""),
        request_summary=_summarize(working_context_text, settings.trace.preview_chars),
        response_summary=_summarize(response_summary, settings.trace.preview_chars),
    )


async def _call_chat(api, messages, *, kwargs: dict, **extra):
    timeout_sec = float(kwargs.pop("timeout_sec", 30) or 30)
    async with asyncio.timeout(timeout_sec):
        return await api.ai.chat(messages, **kwargs, **extra)


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
            payload = json.loads(arguments)
        else:
            payload = arguments or {}
        if not isinstance(payload, dict):
            payload = {}
        calls.append(AgentToolCall(name=name, arguments=payload))
    return calls


def _extract_text(response) -> str:
    if isinstance(response, str):
        return response
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        if message is not None and getattr(message, "content", None) is not None:
            return str(message.content)
        if getattr(choices[0], "text", None):
            return str(choices[0].text)
    if getattr(response, "content", None):
        return str(response.content)
    return ""


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


def _log_llm_chain(working_context, messages, tool_calls, text, settings) -> None:
    """Log the full LLM input/output chain when log_llm_chain is enabled.

    Skips the system prompt. Escapes user-facing text to avoid multi-line breakage.
    """
    if not settings.trace.log_llm_chain:
        return

    chain_logger = logging.getLogger("grok.llm_chain")
    chain_logger.setLevel(logging.INFO)
    # Ensure messages propagate to the root handler
    if not chain_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d [grok.llm_chain] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        chain_logger.addHandler(handler)
    chain_logger.propagate = True

    # User message (skip system prompt at index 0)
    user_msg = messages[1] if len(messages) > 1 else messages[-1]
    user_content = str(user_msg.get("content", "") or "")
    chain_logger.info("=" * 70)
    chain_logger.info("--- USER MESSAGE ---")
    chain_logger.info("%s", pprint.pformat(user_content, width=120, compact=False))

    # Tool calls
    if tool_calls:
        chain_logger.info("-" * 70)
        chain_logger.info("--- MODEL TOOL CALLS ---")
        for tc in tool_calls:
            chain_logger.info("  TOOL: %s", tc.name)
            chain_logger.info("  ARGS:")
            for line in pprint.pformat(tc.arguments, width=120, compact=False).split(
                "\n"
            ):
                chain_logger.info("    %s", line)

    # Tool results (evidence appended after previous round)
    evidence = getattr(working_context, "evidence", None) or []
    if evidence:
        chain_logger.info("-" * 70)
        chain_logger.info("--- TOOL RESULTS ---")
        for block in evidence:
            _log_block(chain_logger, block)

    # Model response text
    if text:
        chain_logger.info("-" * 70)
        chain_logger.info("--- MODEL RESPONSE ---")
        chain_logger.info("%s", pprint.pformat(text, width=120, compact=False))


def _log_block(chain_logger, block) -> None:
    """Log a single evidence block (tool result or error) with indentation."""
    label = block.label or ""
    content = str(block.content or "")
    if block.kind == "tool_error":
        chain_logger.info("  ERROR [%s]:", label)
        for line in content.split("\n"):
            chain_logger.info("    %s", line)
    else:
        chain_logger.info("  [%s]:", label)
        for line in content.split("\n"):
            chain_logger.info("    %s", line[:500])


def _escape_chain(text: str) -> str:
    """Escape newlines and control chars for single-line log output."""
    result = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return result[:5000]
