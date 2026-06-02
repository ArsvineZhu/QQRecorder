import inspect
import json
from typing import Any


async def resolve_awaitable(value):
    if inspect.isawaitable(value):
        return await value
    return value


def sender_name(event) -> str:
    for field in ("card", "nickname", "sender_nickname", "user_name"):
        value = getattr(event, field, None)
        if value:
            return str(value)
    return str(getattr(event, "user_id", "") or "")


def chat_identity(event, source_msg) -> tuple[str, str]:
    chat_type = str(getattr(source_msg, "chat_type", "") or "")
    if not chat_type:
        chat_type = (
            "group" if getattr(event, "group_id", None) is not None else "private"
        )
    chat_id = str(
        getattr(source_msg, "group_id", None)
        or getattr(event, "group_id", None)
        or getattr(source_msg, "user_id", "")
        or getattr(event, "user_id", "")
    )
    return chat_type, chat_id


def json_list(items: list[str]) -> str:
    return json.dumps(items, ensure_ascii=False)


def json_payload(payload: dict[str, Any], limit: int) -> str:
    normalized = {
        key: normalize_log_value(value, limit) for key, value in payload.items()
    }
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def normalize_log_value(value: Any, limit: int):
    if isinstance(value, str):
        return clip_text(value, limit)
    if isinstance(value, list):
        return [normalize_log_value(item, limit) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_log_value(item, limit) for key, item in value.items()
        }
    return value


def clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"
