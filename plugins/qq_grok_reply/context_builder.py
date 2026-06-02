from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from .compat import import_sibling_plugin_module
from .config import ReplyPluginSettings

unescape_text = import_sibling_plugin_module("qq_recorder.text_utils").unescape_text


@dataclass
class BuiltContext:
    context_ids: list[str]
    quoted_block: str
    recent_block: str
    current_block: str
    variant: str
    chat_type: str = ""
    trigger_reason: str = ""
    current_time: str = ""
    sender_name: str = ""
    max_reply_chars: int = 0


async def build_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event=None,
    trigger_reason: str = "",
    sender_name: str | None = None,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
    chat_id = str(source_msg.group_id if is_group else source_msg.user_id)
    recent_limit = (
        settings.context.recent_limit_group
        if is_group
        else settings.context.recent_limit_private
    )
    total_chars = (
        settings.context.total_chars_group
        if is_group
        else settings.context.total_chars_private
    )
    quote_chars = (
        settings.context.quote_chars_group
        if is_group
        else settings.context.quote_chars_private
    )
    recent_chars = (
        settings.context.recent_chars_group
        if is_group
        else settings.context.recent_chars_private
    )

    quoted_block = ""
    context_ids: list[str] = [str(source_msg.message_id)]
    reply_to_id = _first_reply_id(source_msg)
    if reply_to_id:
        quoted_msg = await bridge.get_message(reply_to_id)
        if quoted_msg is not None:
            quoted_block = _trim(
                _render_line(quoted_msg, sender_name=_display_name(quoted_msg)),
                quote_chars,
            )
            if str(quoted_msg.message_id) not in context_ids:
                context_ids.append(str(quoted_msg.message_id))

    recent_messages = await bridge.get_recent(chat_type, chat_id, recent_limit + 2)
    recent_candidates: list[tuple[str, str]] = []
    recent_lines: list[str] = []
    for message in recent_messages:
        message_id = str(message.message_id)
        if message_id == str(source_msg.message_id) or message_id == reply_to_id:
            continue
        rendered = _trim(
            _render_line(message, sender_name=_display_name(message)),
            recent_chars + 32,
        )
        recent_candidates.append((message_id, rendered))
        context_ids.append(message_id)
        if len(recent_candidates) >= recent_limit:
            break
    for _message_id, rendered in reversed(recent_candidates):
        recent_lines.append(rendered)

    current_text = _current_message_text(event, source_msg, settings, trigger_reason)
    current_sender = sender_name or _display_name(source_msg)
    current_budget = max(1, total_chars - len(quoted_block))
    current_block = _trim(
        _render_line(
            source_msg, sender_name=current_sender, text_override=current_text
        ),
        current_budget,
    )
    if len(current_block) > total_chars:
        current_block = current_block[:total_chars]

    return BuiltContext(
        context_ids=_unique(context_ids),
        quoted_block=quoted_block,
        recent_block="\n".join(recent_lines),
        current_block=current_block[:total_chars],
        variant="group_compact" if is_group else "private_contextual",
        chat_type=chat_type,
        trigger_reason=trigger_reason,
        current_time=_format_full_time(getattr(source_msg, "timestamp", None)),
        sender_name=current_sender,
        max_reply_chars=_prompt_char_limit(settings, is_group),
    )


def _render_message(message) -> str:
    raw = unescape_text(str(getattr(message, "raw_message", "") or ""))
    labels: list[str] = []
    if getattr(message, "has_image", False):
        labels.append("[表情]" if _is_sticker_message(message) else "[图片]")
    if getattr(message, "has_forward", False):
        labels.append("[合并转发]")
    if getattr(message, "has_reply", False):
        labels.append("[回复]")
    if getattr(message, "has_app_share", False):
        labels.append(_share_label(message))
    label_text = " ".join(labels)
    if raw and label_text:
        return f"{raw} {label_text}"
    if raw:
        return raw
    if label_text:
        return label_text
    return ""


def _render_line(message, *, sender_name: str, text_override: str | None = None) -> str:
    time_label = _format_short_time(getattr(message, "timestamp", None))
    text = text_override if text_override is not None else _render_message(message)
    return f"[{time_label}] {sender_name}: {text or '无'}"


def _current_message_text(
    event, source_msg, settings: ReplyPluginSettings, trigger_reason: str
) -> str:
    raw_message = str(
        getattr(event, "raw_message", None)
        or getattr(source_msg, "raw_message", "")
        or ""
    )
    raw_message = unescape_text(raw_message)
    if trigger_reason == "prefix" or trigger_reason.startswith("prefix:"):
        raw_message = _strip_prefix(raw_message, settings.trigger.prefixes)
    message_stub = _message_with_raw(source_msg, raw_message)
    return _render_message(message_stub)


def _message_with_raw(message, raw_message: str):
    view = SimpleNamespace()
    for field in (
        "has_image",
        "has_forward",
        "has_reply",
        "has_app_share",
        "images",
        "app_shares",
    ):
        setattr(
            view, field, getattr(message, field, False if field != "images" else [])
        )
    view.raw_message = raw_message
    return view


def _display_name(message) -> str:
    for field in ("sender_card", "card", "sender_nickname", "nickname", "user_name"):
        value = getattr(message, field, None)
        if value:
            return str(value)
    return str(getattr(message, "user_id", "") or "")


def _share_label(message) -> str:
    app_shares = getattr(message, "app_shares", []) or []
    if app_shares:
        first = app_shares[0]
        title = str(getattr(first, "title", "") or "").strip()
        app_name = str(getattr(first, "app_name", "") or "").strip()
        share_text = title or app_name
        if share_text:
            return f"[分享: {share_text}]"
    return "[分享]"


def _strip_prefix(raw_message: str, prefixes: list[str]) -> str:
    stripped = raw_message.strip()
    if not stripped:
        return stripped
    parts = stripped.split(maxsplit=1)
    if parts and any(parts[0].lower() == value.lower() for value in prefixes):
        return parts[1] if len(parts) > 1 else ""
    return stripped


def _is_sticker_message(message) -> bool:
    images = getattr(message, "images", []) or []
    return bool(images) and all(getattr(image, "is_sticker", False) for image in images)


def _format_short_time(timestamp) -> str:
    dt = _coerce_datetime(timestamp)
    return dt.strftime("%H:%M")


def _format_full_time(timestamp) -> str:
    dt = _coerce_datetime(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M")


def _coerce_datetime(timestamp) -> datetime:
    if isinstance(timestamp, datetime):
        return timestamp
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp)
    return datetime.fromtimestamp(0)


def _prompt_char_limit(settings: ReplyPluginSettings, is_group: bool) -> int:
    if is_group:
        return min(
            500, settings.send.group_max_chars_per_part * settings.send.group_max_parts
        )
    return min(
        1200,
        settings.send.private_max_chars_per_part * settings.send.private_max_parts,
    )


def _first_reply_id(message) -> str | None:
    replies = getattr(message, "replies", [])
    if not replies:
        return None
    reply_id = getattr(replies[0], "reply_to_message_id", None)
    return str(reply_id) if reply_id else None


def _trim(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
