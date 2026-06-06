from __future__ import annotations

from typing import Any

from ..prompt_synthesizer import build_model_messages

_VALID_TURN_TYPES = {"user", "assistant", "tool"}


def build_initial_messages(
    working_context,
    settings,
    transcript_turns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    base_messages = build_model_messages(working_context, settings)
    transcript_turns = normalize_transcript_turns(transcript_turns or [])
    replay_messages = render_transcript_messages(transcript_turns)
    working_context.replay_message_ids = collect_replay_message_ids(transcript_turns)
    return [base_messages[0], *replay_messages, base_messages[1]]


def build_transcript_turns(
    *,
    source_message: dict[str, Any],
    final_text: str,
    messages_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    user_turn = {
        "type": "user",
        "content": str(source_message.get("raw_message", "") or ""),
        "message_id": str(source_message.get("message_id", "") or ""),
        "timestamp": str(source_message.get("timestamp", "") or ""),
        "sender": str(source_message.get("sender", "") or ""),
        "chat_type": str(source_message.get("chat_type", "") or ""),
        "chat_id": str(source_message.get("chat_id", "") or ""),
        "user_id": str(source_message.get("user_id", "") or ""),
    }
    turns: list[dict[str, Any]] = [user_turn]

    history = messages_history or []
    current_index = _current_user_index(history)
    if current_index >= 0:
        for message in history[current_index + 1 :]:
            turn = _history_message_to_transcript_turn(message)
            if turn is not None:
                turns.append(turn)

    if final_text.strip():
        if (
            not turns
            or turns[-1].get("type") != "assistant"
            or turns[-1].get("content", "") != final_text.strip()
        ):
            turns.append({"type": "assistant", "content": final_text.strip()})
    return turns


def normalize_transcript_turns(
    turns: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        turn_type = str(turn.get("type", "") or "").strip()
        if turn_type not in _VALID_TURN_TYPES:
            continue
        item = dict(turn)
        item["type"] = turn_type
        normalized.append(item)
    return normalized


def render_transcript_messages(
    turns: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for turn in normalize_transcript_turns(turns):
        turn_type = str(turn.get("type", "") or "")
        if turn_type == "user":
            rendered.append({"role": "user", "content": _render_user_turn(turn)})
            continue
        if turn_type == "assistant":
            message: dict[str, Any] = {
                "role": "assistant",
                "content": str(turn.get("content", "") or ""),
            }
            reasoning_content = turn.get("reasoning_content")
            if reasoning_content is not None:
                message["reasoning_content"] = reasoning_content
            tool_calls = turn.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                message["tool_calls"] = tool_calls
            rendered.append(message)
            continue
        if turn_type == "tool":
            rendered.append(
                {
                    "role": "tool",
                    "tool_call_id": str(turn.get("tool_call_id", "") or ""),
                    "content": str(turn.get("content", "") or ""),
                }
            )
    return rendered


def collect_replay_message_ids(turns: list[dict[str, Any]] | None) -> set[str]:
    ids: set[str] = set()
    for turn in normalize_transcript_turns(turns):
        if str(turn.get("type", "") or "") != "user":
            continue
        message_id = str(turn.get("message_id", "") or "").strip()
        if message_id:
            ids.add(message_id)
    return ids


def trim_transcript_turns(
    turns: list[dict[str, Any]] | None,
    *,
    max_messages: int,
) -> list[dict[str, Any]]:
    normalized = normalize_transcript_turns(turns)
    if max_messages <= 0:
        return []
    if len(normalized) <= max_messages:
        trimmed = list(normalized)
    else:
        trimmed = list(normalized[-max_messages:])
    for index, turn in enumerate(trimmed):
        if str(turn.get("type", "") or "") == "user":
            return trimmed[index:]
    return []


def _render_user_turn(turn: dict[str, Any]) -> str:
    content = str(turn.get("content", "") or "").strip()
    chat_type = str(turn.get("chat_type", "") or "").strip()
    sender = str(turn.get("sender", "") or "").strip()
    user_id = str(turn.get("user_id", "") or "").strip()
    timestamp = str(turn.get("timestamp", "") or "").strip()
    if chat_type == "group":
        prefix_parts = []
        if timestamp:
            prefix_parts.append(timestamp)
        if sender:
            prefix_parts.append(sender)
        if user_id:
            prefix_parts.append(f"user_id={user_id}")
        prefix = " | ".join(prefix_parts)
        if prefix:
            return f"[历史群消息] {prefix}: {content}"
        return f"[历史群消息] {content}"
    return content


def _current_user_index(messages_history: list[dict[str, Any]]) -> int:
    for index in range(len(messages_history) - 1, -1, -1):
        message = messages_history[index]
        if str(message.get("role", "") or "") != "user":
            continue
        content = str(message.get("content", "") or "")
        if content.startswith("# 本轮回复任务"):
            return index
    return -1


def _history_message_to_transcript_turn(
    message: dict[str, Any],
) -> dict[str, Any] | None:
    role = str(message.get("role", "") or "").strip()
    if role == "assistant":
        turn: dict[str, Any] = {
            "type": "assistant",
            "content": str(message.get("content", "") or ""),
        }
        if message.get("reasoning_content") is not None:
            turn["reasoning_content"] = message.get("reasoning_content")
        if isinstance(message.get("tool_calls"), list) and message.get("tool_calls"):
            turn["tool_calls"] = message.get("tool_calls")
        return turn
    if role == "tool":
        return {
            "type": "tool",
            "tool_call_id": str(message.get("tool_call_id", "") or ""),
            "tool_name": str(message.get("tool_name", "") or ""),
            "content": str(message.get("content", "") or ""),
        }
    return None
