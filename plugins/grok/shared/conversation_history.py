from __future__ import annotations

from typing import Any

from ..agent.prompt import build_model_messages


def build_initial_messages(
    working_context,
    settings,
    transcript: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    base_messages = build_model_messages(working_context, settings)
    transcript = sanitize_transcript(transcript or [])
    return [base_messages[0], *transcript, base_messages[1]]


def sanitize_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "") or "").strip()
        if role not in {"user", "assistant", "tool"}:
            continue
        sanitized.append(dict(message))
    return sanitized


def to_persisted_transcript(
    messages_history: list[dict[str, Any]] | None,
    *,
    max_messages: int,
) -> list[dict[str, Any]]:
    transcript = [
        dict(message)
        for message in sanitize_transcript(messages_history or [])
        if str(message.get("role", "") or "") != "system"
    ]
    return trim_transcript(transcript, max_messages=max_messages)


def trim_transcript(
    messages: list[dict[str, Any]],
    *,
    max_messages: int,
) -> list[dict[str, Any]]:
    if max_messages <= 0:
        return []
    if len(messages) <= max_messages:
        trimmed = list(messages)
    else:
        trimmed = list(messages[-max_messages:])
    for index, message in enumerate(trimmed):
        if str(message.get("role", "") or "") == "user":
            return trimmed[index:]
    return []
