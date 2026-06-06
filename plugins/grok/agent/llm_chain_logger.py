from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("grok.llm_chain")


def validate_messages_for_chat_api(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    if not messages:
        return [
            {
                "kind": "messages_validation",
                "code": "empty_messages",
                "message": "messages 不能为空",
                "metadata": {},
            }
        ]

    diagnostics.extend(_validate_system_messages(messages))
    diagnostics.extend(_validate_current_user_messages(messages))
    diagnostics.extend(_validate_tool_chain(messages))

    return diagnostics


def render_llm_chain_lines(
    *,
    request_id: str,
    chat_type: str,
    chat_id: str,
    source_message_id: str,
    step: int,
    messages: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
) -> list[str]:
    current_indexes = _current_user_indexes(messages)
    current_index = current_indexes[-1] if current_indexes else -1
    lines = [
        (
            "request"
            f" request_id={request_id} chat={chat_type}:{chat_id}"
            f" source_msg_id={source_message_id} step={step}"
        )
    ]
    for index, message in enumerate(messages):
        role = str(message.get("role", "") or "unknown")
        source = _message_source(index, role, current_index)
        content = str(message.get("content", "") or "")
        preview = _clip_text(_flatten_text(content), 120)
        extras: list[str] = []
        if role == "assistant":
            tool_calls = _tool_calls(message)
            if tool_calls:
                extras.extend(
                    f"tool={_tool_name(item)}"
                    for item in tool_calls
                    if _tool_name(item)
                )
                extras.append(
                    "tools=["
                    + ", ".join(
                        f"{_tool_name(item)}({str(item.get('id', '') or '')})"
                        for item in tool_calls
                    )
                    + "]"
                )
        if role == "tool":
            extras.append(
                f"tool_call_id={str(message.get('tool_call_id', '') or '').strip()}"
            )
        line = (
            f"  [{index}] role={role} source={source} chars={len(content)}"
            f" preview={preview!r}"
        )
        if extras:
            line += " " + " ".join(extras)
        lines.append(line)
    if usage:
        hit = usage.get("prompt_cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens")
        if hit is not None or miss is not None:
            lines.append(
                f"  usage prompt_cache_hit_tokens={hit or 0}"
                f" prompt_cache_miss_tokens={miss or 0}"
            )
    return lines


def log_llm_chain(
    *,
    request_id: str,
    chat_type: str,
    chat_id: str,
    source_message_id: str,
    step: int,
    messages: list[dict[str, Any]],
    response_text: str,
    tool_calls: list[Any],
    usage: dict[str, Any] | None = None,
) -> None:
    for line in render_llm_chain_lines(
        request_id=request_id,
        chat_type=chat_type,
        chat_id=chat_id,
        source_message_id=source_message_id,
        step=step,
        messages=messages,
        usage=usage,
    ):
        logger.info("%s", line)
    if tool_calls:
        logger.info(
            "response request_id=%s step=%d assistant tool_calls=%s",
            request_id,
            step,
            ", ".join(
                f"{getattr(call, 'name', '')}({getattr(call, 'tool_call_id', '')})"
                for call in tool_calls
            ),
        )
    else:
        logger.info(
            "response request_id=%s step=%d assistant final chars=%d preview=%r",
            request_id,
            step,
            len(response_text),
            _clip_text(_flatten_text(response_text), 120),
        )


def _current_user_indexes(messages: list[dict[str, Any]]) -> list[int]:
    return [
        index
        for index, message in enumerate(messages)
        if str(message.get("role", "") or "") == "user"
        and str(message.get("content", "") or "").startswith("# 本轮回复任务")
    ]


def _message_source(index: int, role: str, current_index: int) -> str:
    if role == "system":
        return "system"
    if index == current_index:
        return "current"
    if current_index >= 0 and index < current_index:
        return "history"
    if current_index >= 0 and index > current_index:
        return "turn"
    return "unknown"


def _validate_system_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    system_indexes = [
        index
        for index, message in enumerate(messages)
        if str(message.get("role", "") or "") == "system"
    ]
    if len(system_indexes) > 1:
        diagnostics.append(
            _diag(
                "multiple_system_messages",
                "system message 最多只能有一个",
                indexes=system_indexes,
            )
        )
    if system_indexes and system_indexes[0] != 0:
        diagnostics.append(
            _diag(
                "system_message_not_first",
                "system message 只能位于开头",
                index=system_indexes[0],
            )
        )
    return diagnostics


def _validate_current_user_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_user_indexes = _current_user_indexes(messages)
    if not current_user_indexes:
        return [
            _diag(
                "missing_current_user_message",
                "缺少当前用户消息，无法确认本轮真正要回答的对象",
            )
        ]
    if len(current_user_indexes) > 1:
        return [
            _diag(
                "duplicate_current_user_message",
                "当前用户消息被重复注入了多次",
                indexes=current_user_indexes,
            )
        ]
    return []


def _validate_tool_chain(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    pending_tool_calls: dict[str, dict[str, Any]] = {}
    for index, message in enumerate(messages):
        role = str(message.get("role", "") or "")
        if role == "assistant":
            _collect_pending_tool_calls(
                diagnostics,
                pending_tool_calls,
                message,
                index=index,
            )
            continue
        if role == "tool":
            _consume_tool_result(
                diagnostics,
                pending_tool_calls,
                message,
                index=index,
            )
    diagnostics.extend(_finalize_pending_tool_calls(pending_tool_calls))
    return diagnostics


def _collect_pending_tool_calls(
    diagnostics: list[dict[str, Any]],
    pending_tool_calls: dict[str, dict[str, Any]],
    message: dict[str, Any],
    *,
    index: int,
) -> None:
    for tool_call in _tool_calls(message):
        tool_call_id = str(tool_call.get("id", "") or "").strip()
        if not tool_call_id:
            diagnostics.append(
                _diag(
                    "assistant_tool_call_missing_id",
                    "assistant tool_calls 缺少 id",
                    index=index,
                )
            )
            continue
        pending_tool_calls[tool_call_id] = {
            "index": index,
            "name": _tool_name(tool_call),
        }


def _consume_tool_result(
    diagnostics: list[dict[str, Any]],
    pending_tool_calls: dict[str, dict[str, Any]],
    message: dict[str, Any],
    *,
    index: int,
) -> None:
    tool_call_id = str(message.get("tool_call_id", "") or "").strip()
    if not tool_call_id or tool_call_id not in pending_tool_calls:
        diagnostics.append(
            _diag(
                "orphan_tool_message",
                "tool message 没有匹配到前面的 assistant tool call",
                index=index,
                tool_call_id=tool_call_id,
            )
        )
        return
    pending_tool_calls.pop(tool_call_id, None)


def _finalize_pending_tool_calls(
    pending_tool_calls: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for tool_call_id, meta in pending_tool_calls.items():
        diagnostics.append(
            _diag(
                "missing_tool_result",
                "assistant 发起了 tool call，但后面缺少对应的 tool result",
                tool_call_id=tool_call_id,
                tool_name=meta.get("name", ""),
                index=meta.get("index", -1),
            )
        )
    return diagnostics


def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("tool_calls") or []
    return [item for item in raw if isinstance(item, dict)]


def _tool_name(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function", {}) or {}
    return str(function.get("name", "") or "").strip()


def _flatten_text(value: str) -> str:
    return value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


def _clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _diag(code: str, message: str, **metadata: Any) -> dict[str, Any]:
    return {
        "kind": "messages_validation",
        "code": code,
        "message": message,
        "metadata": metadata,
    }


def usage_from_response(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    try:
        return json.loads(json.dumps(usage, default=lambda value: value.__dict__))
    except TypeError:
        return {}
