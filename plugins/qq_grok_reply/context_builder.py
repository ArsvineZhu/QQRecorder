from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from .compat import import_sibling_plugin_module
from .config import ReplyPluginSettings
from .topic_analyzer import TopicAnalysis, analyze_topic, validate_topic_analysis

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
    topic_title: str = ""
    topic_summary: str = ""
    topic_participants: list[str] = field(default_factory=list)
    topic_confidence: float = 0.0
    topic_candidate_count: int = 0
    topic_error_code: str = ""
    topic_fallback_used: bool = False
    topic_excluded_ids_json: str = "[]"


async def build_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event=None,
    trigger_reason: str = "",
    sender_name: str | None = None,
    analyzer_api=None,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
    if _should_use_topic_ai(settings, analyzer_api):
        return await _build_topic_context(
            source_msg,
            bridge,
            settings,
            event=event,
            trigger_reason=trigger_reason,
            sender_name=sender_name,
            analyzer_api=analyzer_api,
            is_group=is_group,
        )
    return await _build_recent_context(
        source_msg,
        bridge,
        settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        recent_limit_override=None,
    )


async def _build_topic_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event,
    trigger_reason: str,
    sender_name: str | None,
    analyzer_api,
    is_group: bool,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    chat_id = str(source_msg.group_id if is_group else source_msg.user_id)
    candidate_limit = (
        settings.context.candidate_limit_group
        if is_group
        else settings.context.candidate_limit_private
    )
    since_minutes = (
        settings.context.candidate_time_window_minutes_group
        if is_group
        else settings.context.candidate_time_window_minutes_private
    )
    max_selected = (
        settings.context.selected_max_messages_group
        if is_group
        else settings.context.selected_max_messages_private
    )

    try:
        candidates = await bridge.get_candidates(
            chat_type,
            chat_id,
            limit=candidate_limit,
            since_minutes=since_minutes,
            before_or_at=getattr(source_msg, "timestamp", None),
        )
    except AttributeError:
        candidates = await bridge.get_recent(chat_type, chat_id, candidate_limit)
    except Exception:
        fallback = await _fallback_context(
            source_msg, bridge, settings, event, trigger_reason, sender_name, is_group
        )
        fallback.topic_error_code = "topic_candidate_read_failed"
        return fallback

    candidate_by_id = {str(message.message_id): message for message in candidates}
    current_id = str(source_msg.message_id)
    if current_id not in candidate_by_id:
        candidates.insert(0, source_msg)
        candidate_by_id[current_id] = source_msg

    reply_to_id = _first_reply_id(source_msg)
    if reply_to_id and reply_to_id not in candidate_by_id:
        quoted_msg = await bridge.get_message(reply_to_id)
        if quoted_msg is not None:
            candidates.append(quoted_msg)
            candidate_by_id[reply_to_id] = quoted_msg

    current_text = _current_message_text(event, source_msg, settings, trigger_reason)
    payload = _topic_payload(
        source_msg,
        candidates,
        settings,
        current_text=current_text,
        current_sender=sender_name or _display_name(source_msg),
        reply_to_id=reply_to_id,
        max_selected=max_selected,
    )
    analysis = await analyze_topic(analyzer_api, payload=payload, settings=settings)
    analysis = validate_topic_analysis(
        analysis,
        candidate_ids=set(candidate_by_id),
        current_message_id=current_id,
        min_confidence=settings.topic_analyzer.min_confidence,
    )
    analysis.candidate_count = len(candidate_by_id)
    if analysis.error_code:
        fallback = await _fallback_context(
            source_msg, bridge, settings, event, trigger_reason, sender_name, is_group
        )
        fallback.topic_title = analysis.topic_title
        fallback.topic_summary = analysis.topic_summary
        fallback.topic_confidence = analysis.confidence
        fallback.topic_candidate_count = analysis.candidate_count
        fallback.topic_error_code = analysis.error_code
        fallback.topic_fallback_used = True
        fallback.topic_excluded_ids_json = analysis.excluded_ids_json()
        return fallback

    selected_ids = _selected_ids_with_priority(
        analysis.selected_message_ids,
        current_id=current_id,
        reply_to_id=reply_to_id,
        max_selected=max_selected,
    )
    selected_messages = [
        candidate_by_id[item] for item in selected_ids if item in candidate_by_id
    ]
    return _assemble_context(
        source_msg,
        selected_messages,
        settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        quoted_msg=candidate_by_id.get(reply_to_id or ""),
        analysis=analysis,
    )


async def _fallback_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    event,
    trigger_reason: str,
    sender_name: str | None,
    is_group: bool,
) -> BuiltContext:
    recent_limit = (
        settings.context.fallback_recent_limit_group
        if is_group
        else settings.context.fallback_recent_limit_private
    )
    built = await _build_recent_context(
        source_msg,
        bridge,
        settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        recent_limit_override=recent_limit,
    )
    built.topic_fallback_used = True
    return built


async def _build_recent_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event=None,
    trigger_reason: str = "",
    sender_name: str | None = None,
    recent_limit_override: int | None,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
    chat_id = str(source_msg.group_id if is_group else source_msg.user_id)
    recent_limit = recent_limit_override or (
        settings.context.recent_limit_group
        if is_group
        else settings.context.recent_limit_private
    )

    reply_to_id = _first_reply_id(source_msg)
    quoted_msg = await bridge.get_message(reply_to_id) if reply_to_id else None
    recent_messages = await bridge.get_recent(chat_type, chat_id, recent_limit + 2)
    recent_selected = []
    for message in recent_messages:
        message_id = str(message.message_id)
        if message_id == str(source_msg.message_id) or message_id == reply_to_id:
            continue
        recent_selected.append(message)
        if len(recent_selected) >= recent_limit:
            break
    return _assemble_context(
        source_msg,
        recent_selected,
        settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        quoted_msg=quoted_msg,
        analysis=None,
    )


def _assemble_context(
    source_msg,
    recent_messages: list[Any],
    settings: ReplyPluginSettings,
    *,
    event,
    trigger_reason: str,
    sender_name: str | None,
    quoted_msg,
    analysis: TopicAnalysis | None,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
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
    if quoted_msg is not None:
        quoted_block = _trim(
            _render_line(
                quoted_msg, sender_name=_display_name(quoted_msg), settings=settings
            ),
            quote_chars,
        )
        context_ids.append(str(quoted_msg.message_id))

    recent_lines: list[str] = []
    for message in recent_messages:
        message_id = str(message.message_id)
        if message_id == str(source_msg.message_id):
            continue
        if quoted_msg is not None and message_id == str(quoted_msg.message_id):
            continue
        rendered = _trim(
            _render_line(
                message, sender_name=_display_name(message), settings=settings
            ),
            recent_chars + settings.context.forward_max_chars + 32,
        )
        recent_lines.append(rendered)
        context_ids.append(message_id)

    current_text = _current_message_text(event, source_msg, settings, trigger_reason)
    current_sender = sender_name or _display_name(source_msg)
    current_budget = max(1, total_chars - len(quoted_block))
    current_block = _trim(
        _render_line(
            source_msg,
            sender_name=current_sender,
            text_override=current_text,
            settings=settings,
        ),
        current_budget,
    )
    recent_block = _trim_to_budget(
        "\n".join(recent_lines), total_chars - len(current_block) - len(quoted_block)
    )
    participants = []
    if analysis is not None:
        participants = [
            f"{item.name}（{item.role}）" if item.role else item.name
            for item in analysis.participants
            if item.name
        ]

    return BuiltContext(
        context_ids=_unique(context_ids),
        quoted_block=quoted_block,
        recent_block=recent_block,
        current_block=current_block[:total_chars],
        variant="group_topic_ai"
        if is_group and analysis
        else ("group_compact" if is_group else "private_contextual"),
        chat_type=chat_type,
        trigger_reason=trigger_reason,
        current_time=_format_full_time(getattr(source_msg, "timestamp", None)),
        sender_name=current_sender,
        max_reply_chars=_prompt_char_limit(settings, is_group),
        topic_title=analysis.topic_title if analysis else "",
        topic_summary=analysis.topic_summary if analysis else "",
        topic_participants=participants,
        topic_confidence=analysis.confidence if analysis else 0.0,
        topic_candidate_count=analysis.candidate_count if analysis else 0,
        topic_error_code=analysis.error_code if analysis else "",
        topic_fallback_used=analysis.fallback_used if analysis else False,
        topic_excluded_ids_json=analysis.excluded_ids_json() if analysis else "[]",
    )


def _topic_payload(
    source_msg,
    candidates: list[Any],
    settings: ReplyPluginSettings,
    *,
    current_text: str,
    current_sender: str,
    reply_to_id: str | None,
    max_selected: int,
) -> dict[str, Any]:
    candidate_items = []
    for message in reversed(candidates):
        message_id = str(message.message_id)
        candidate_items.append(
            {
                "id": message_id,
                "sender_id": str(getattr(message, "user_id", "") or ""),
                "sender_name": _display_name(message),
                "time": _format_full_time(getattr(message, "timestamp", None)),
                "content": _render_message(message, settings=settings),
                "reply_to_message_id": _first_reply_id(message),
                "features": _message_features(message),
                "forward_summary": _render_forward_summary(message, settings),
            }
        )
    return {
        "current_message": {
            "id": str(source_msg.message_id),
            "sender_name": current_sender,
            "content": current_text,
            "reply_to_message_id": reply_to_id,
        },
        "candidate_messages": candidate_items,
        "max_select_messages": max_selected,
        "max_summary_chars": settings.topic_analyzer.max_summary_chars,
    }


def _render_message(message, *, settings: ReplyPluginSettings) -> str:
    raw = unescape_text(str(getattr(message, "raw_message", "") or ""))
    labels: list[str] = []
    if getattr(message, "has_image", False):
        labels.append("[表情]" if _is_sticker_message(message) else "[图片]")
    if getattr(message, "has_forward", False):
        summary = _render_forward_summary(message, settings)
        labels.append(f"[合并转发]\n{summary}" if summary else "[合并转发]")
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


def _render_forward_summary(message, settings: ReplyPluginSettings) -> str:
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


def _render_line(
    message,
    *,
    sender_name: str,
    settings: ReplyPluginSettings,
    text_override: str | None = None,
) -> str:
    time_label = _format_short_time(getattr(message, "timestamp", None))
    text = (
        text_override
        if text_override is not None
        else _render_message(message, settings=settings)
    )
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
    return _render_message(message_stub, settings=settings)


def _message_with_raw(message, raw_message: str):
    view = SimpleNamespace()
    for attr_name in (
        "has_image",
        "has_forward",
        "has_reply",
        "has_app_share",
        "images",
        "app_shares",
        "forward_messages",
    ):
        setattr(
            view,
            attr_name,
            getattr(message, attr_name, False if attr_name != "images" else []),
        )
    view.raw_message = raw_message
    return view


def _display_name(message) -> str:
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


def _message_features(message) -> list[str]:
    features = []
    for attr, label in (
        ("has_image", "image"),
        ("has_reply", "reply"),
        ("has_forward", "forward"),
        ("has_at", "at"),
        ("has_app_share", "share"),
    ):
        if getattr(message, attr, False):
            features.append(label)
    return features


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
    first = replies[0]
    value = getattr(first, "reply_to_message_id", None)
    return str(value) if value else None


def _selected_ids_with_priority(
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
    return _unique(result)[-max_selected:]


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _trim_to_budget(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    return _trim(text, budget)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _should_use_topic_ai(settings: ReplyPluginSettings, analyzer_api) -> bool:
    return (
        settings.context.mode == "topic_ai"
        and settings.topic_analyzer.enabled
        and analyzer_api is not None
    )
