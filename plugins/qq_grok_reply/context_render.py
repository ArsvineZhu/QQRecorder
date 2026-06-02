import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from .compat import import_sibling_plugin_module
from .config import ReplyPluginSettings

unescape_text = import_sibling_plugin_module("qq_recorder.text_utils").unescape_text


def render_message(message, *, settings: ReplyPluginSettings) -> str:
    raw = visible_raw_text(message)
    labels: list[str] = []
    if has_image_marker(message):
        labels.append("[表情]" if is_sticker_message(message) else "[图片]")
    if has_forward_marker(message):
        summary = render_forward_summary(message, settings)
        labels.append(f"[合并转发]\n{summary}" if summary else "[合并转发]")
    if has_reply_marker(message):
        labels.append("[回复]")
    if has_app_share_marker(message):
        labels.append(share_label(message))
    label_text = " ".join(labels)
    if raw and label_text:
        return f"{raw} {label_text}"
    if raw:
        return raw
    if label_text:
        return label_text
    return ""


def visible_raw_text(message) -> str:
    raw = raw_message_text(message)
    if not raw:
        return ""
    raw = re.sub(r"\[CQ:[^\]]+\]", "", raw)
    lines = [line.strip() for line in raw.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def render_forward_summary(message, settings: ReplyPluginSettings) -> str:
    forwards = list(getattr(message, "forward_messages", []) or [])
    if not forwards:
        return ""
    forwards.sort(key=lambda item: (getattr(item, "depth", 0), getattr(item, "id", 0)))
    lines = ["合并转发摘要："]
    used = len(lines[0])
    truncated = False
    for item in forwards[: settings.context.forward_max_items]:
        nickname = str(
            getattr(item, "nickname", "") or getattr(item, "user_id", "") or "未知"
        )
        summary = unescape_text(str(getattr(item, "content_summary", "") or "")).strip()
        if not summary:
            continue
        line = f"{nickname}：{summary}"
        next_used = used + len(line) + 1
        if next_used > settings.context.forward_max_chars:
            truncated = True
            break
        lines.append(line)
        used = next_used
    if len(forwards) > settings.context.forward_max_items:
        truncated = True
    if truncated:
        lines.append("……已截断。")
    return "\n".join(lines) if len(lines) > 1 else ""


def render_line(
    message,
    *,
    sender_name: str,
    settings: ReplyPluginSettings,
    text_override: str | None = None,
) -> str:
    time_label = format_short_time(getattr(message, "timestamp", None))
    if text_override is not None:
        text = text_override
    else:
        text = render_message(message, settings=settings)
    return f"[{time_label}] {sender_name}: {text or '无'}"


def current_message_text(
    event, source_msg, settings: ReplyPluginSettings, trigger_reason: str
) -> str:
    raw_message = str(
        getattr(event, "raw_message", None)
        or getattr(source_msg, "raw_message", "")
        or ""
    )
    raw_message = unescape_text(raw_message)
    if trigger_reason == "prefix" or trigger_reason.startswith("prefix:"):
        raw_message = strip_prefix(raw_message, settings.trigger.prefixes)
    message_stub = message_with_raw(source_msg, raw_message)
    return render_message(message_stub, settings=settings)


def message_with_raw(message, raw_message: str):
    view = message_view(message)
    view.raw_message = raw_message
    return view


def message_view(message, **overrides):
    view = SimpleNamespace()
    list_fields = {"images", "replies", "app_shares", "forward_messages"}
    for attr_name in (
        "message_id",
        "timestamp",
        "chat_type",
        "user_id",
        "group_id",
        "has_image",
        "has_forward",
        "has_reply",
        "has_app_share",
        "has_at",
        "images",
        "replies",
        "app_shares",
        "forward_messages",
        "sender_nickname",
        "sender_card",
        "nickname",
        "card",
        "user_name",
        "raw_message",
    ):
        default = [] if attr_name in list_fields else False
        setattr(view, attr_name, getattr(message, attr_name, default))
    for attr_name, value in overrides.items():
        setattr(view, attr_name, value)
    return view


def display_name(message) -> str:
    for attr_name in (
        "sender_card",
        "card",
        "sender_nickname",
        "nickname",
        "user_name",
    ):
        value = getattr(message, attr_name, None)
        if value:
            return str(value)
    return str(getattr(message, "user_id", "") or "")


def share_label(message) -> str:
    app_shares = getattr(message, "app_shares", []) or []
    if app_shares:
        first = app_shares[0]
        title = str(getattr(first, "title", "") or "").strip()
        app_name = str(getattr(first, "app_name", "") or "").strip()
        share_text = title or app_name
        if share_text:
            return f"[分享: {share_text}]"
    return "[分享]"


def message_features(message) -> list[str]:
    features = []
    for attr, label in (
        ("image", "image"),
        ("reply", "reply"),
        ("forward", "forward"),
        ("has_at", "at"),
        ("share", "share"),
    ):
        if has_feature(message, attr):
            features.append(label)
    return features


def has_feature(message, feature: str) -> bool:
    if feature == "image":
        return has_image_marker(message)
    if feature == "reply":
        return has_reply_marker(message)
    if feature == "forward":
        return has_forward_marker(message)
    if feature == "share":
        return has_app_share_marker(message)
    return bool(getattr(message, feature, False))


def has_image_marker(message) -> bool:
    raw = raw_message_text(message)
    return bool(getattr(message, "has_image", False)) or "[CQ:image" in raw


def has_reply_marker(message) -> bool:
    raw = raw_message_text(message)
    return bool(getattr(message, "has_reply", False)) or "[CQ:reply" in raw


def has_forward_marker(message) -> bool:
    raw = raw_message_text(message)
    return bool(getattr(message, "has_forward", False)) or "[CQ:forward" in raw


def has_app_share_marker(message) -> bool:
    raw = raw_message_text(message)
    return bool(getattr(message, "has_app_share", False)) or "[CQ:json" in raw


def raw_message_text(message) -> str:
    return unescape_text(str(getattr(message, "raw_message", "") or ""))


def extract_forward_id(raw_message: str) -> str:
    match = re.search(r"\[CQ:forward,[^\]]*?\bid=([^,\]]+)", raw_message)
    return match.group(1).strip() if match else ""


def strip_prefix(raw_message: str, prefixes: list[str]) -> str:
    stripped = raw_message.strip()
    if not stripped:
        return stripped
    parts = stripped.split(maxsplit=1)
    if parts and any(parts[0].lower() == value.lower() for value in prefixes):
        return parts[1] if len(parts) > 1 else ""
    return stripped


def is_sticker_message(message) -> bool:
    images = getattr(message, "images", []) or []
    return bool(images) and all(getattr(image, "is_sticker", False) for image in images)


def format_short_time(timestamp) -> str:
    dt = coerce_datetime(timestamp)
    return dt.strftime("%H:%M")


def format_full_time(timestamp) -> str:
    dt = coerce_datetime(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M")


def coerce_datetime(timestamp) -> datetime:
    if isinstance(timestamp, datetime):
        return timestamp
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp)
    return datetime.fromtimestamp(0)


def prompt_char_limit(settings: ReplyPluginSettings, is_group: bool) -> int:
    if is_group:
        return min(
            500, settings.send.group_max_chars_per_part * settings.send.group_max_parts
        )
    return min(
        1200,
        settings.send.private_max_chars_per_part * settings.send.private_max_parts,
    )


def first_reply_id(message) -> str | None:
    replies = getattr(message, "replies", [])
    if not replies:
        return None
    first = replies[0]
    value = getattr(first, "reply_to_message_id", None)
    return str(value) if value else None


def selected_ids_with_priority(
    selected_ids: list[str],
    *,
    current_id: str,
    reply_to_id: str | None,
    max_selected: int,
) -> list[str]:
    result = []
    if reply_to_id:
        result.append(reply_to_id)
    result.extend(selected_ids)
    result.append(current_id)
    return unique(result)[-max_selected:]


def chronological_messages(messages: list[Any]) -> list[Any]:
    return sorted(
        messages,
        key=lambda message: coerce_datetime(getattr(message, "timestamp", None)),
    )


def trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def trim_to_budget(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    return trim(text, budget)


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def should_use_topic_ai(settings: ReplyPluginSettings, analyzer_api) -> bool:
    return (
        settings.context.mode == "topic_ai"
        and settings.topic_analyzer.enabled
        and analyzer_api is not None
    )
