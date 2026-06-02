from typing import Any

from .config import ReplyPluginSettings
from .context_legacy_forward import (
    hydrate_legacy_forward_message,
    hydrate_legacy_forward_messages,
)
from .context_render import (
    chronological_messages,
    current_message_text,
    display_name,
    first_reply_id,
    format_full_time,
    message_features,
    prompt_char_limit,
    render_forward_summary,
    render_line,
    render_message,
    selected_ids_with_priority,
    should_use_topic_ai,
    trim,
    trim_to_budget,
    unique,
)
from .context_types import BuiltContext, TopicContextError
from .topic_analyzer import TopicAnalysis, analyze_topic, validate_topic_analysis


async def build_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event=None,
    trigger_reason: str = "",
    sender_name: str | None = None,
    analyzer_api=None,
    runtime_api=None,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
    if should_use_topic_ai(settings, analyzer_api):
        return await _build_topic_context(
            source_msg,
            bridge,
            settings,
            event=event,
            trigger_reason=trigger_reason,
            sender_name=sender_name,
            analyzer_api=analyzer_api,
            runtime_api=runtime_api,
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
        runtime_api=runtime_api,
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
    runtime_api,
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
    except Exception as exc:
        analysis = TopicAnalysis(error_code="topic_candidate_read_failed")
        if not settings.topic_analyzer.fallback_to_recent:
            raise TopicContextError(analysis) from exc
        fallback = await _fallback_context(
            source_msg,
            bridge,
            settings,
            event,
            trigger_reason,
            sender_name,
            is_group,
            runtime_api,
        )
        fallback.topic_error_code = analysis.error_code
        return fallback

    source_msg = await hydrate_legacy_forward_message(source_msg, runtime_api, settings)
    assert source_msg is not None
    candidates = await hydrate_legacy_forward_messages(
        candidates, runtime_api, settings
    )
    candidate_by_id = {str(message.message_id): message for message in candidates}
    current_id = str(source_msg.message_id)
    if current_id not in candidate_by_id:
        candidates.insert(0, source_msg)
        candidate_by_id[current_id] = source_msg

    reply_to_id = first_reply_id(source_msg)
    if reply_to_id and reply_to_id not in candidate_by_id:
        quoted_msg = await bridge.get_message(reply_to_id)
        if quoted_msg is not None:
            quoted_msg = await hydrate_legacy_forward_message(
                quoted_msg, runtime_api, settings
            )
            candidates.append(quoted_msg)
            candidate_by_id[reply_to_id] = quoted_msg

    current_text = current_message_text(event, source_msg, settings, trigger_reason)
    payload = _topic_payload(
        source_msg,
        candidates,
        settings,
        current_text=current_text,
        current_sender=sender_name or display_name(source_msg),
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
        if not settings.topic_analyzer.fallback_to_recent:
            raise TopicContextError(analysis)
        fallback = await _fallback_context(
            source_msg,
            bridge,
            settings,
            event,
            trigger_reason,
            sender_name,
            is_group,
            runtime_api,
        )
        fallback.topic_title = analysis.topic_title
        fallback.topic_summary = analysis.topic_summary
        fallback.topic_confidence = analysis.confidence
        fallback.topic_candidate_count = analysis.candidate_count
        fallback.topic_error_code = analysis.error_code
        fallback.topic_fallback_used = True
        fallback.topic_excluded_ids_json = analysis.excluded_ids_json()
        return fallback

    selected_ids = selected_ids_with_priority(
        analysis.selected_message_ids,
        current_id=current_id,
        reply_to_id=reply_to_id,
        max_selected=max_selected,
    )
    selected_messages = chronological_messages(
        [candidate_by_id[item] for item in selected_ids if item in candidate_by_id]
    )
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
    runtime_api,
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
        runtime_api=runtime_api,
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
    runtime_api=None,
) -> BuiltContext:
    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
    chat_id = str(source_msg.group_id if is_group else source_msg.user_id)
    recent_limit = recent_limit_override or (
        settings.context.recent_limit_group
        if is_group
        else settings.context.recent_limit_private
    )

    reply_to_id = first_reply_id(source_msg)
    source_msg = await hydrate_legacy_forward_message(source_msg, runtime_api, settings)
    assert source_msg is not None
    quoted_msg = await bridge.get_message(reply_to_id) if reply_to_id else None
    quoted_msg = await hydrate_legacy_forward_message(quoted_msg, runtime_api, settings)
    recent_messages = await bridge.get_recent(chat_type, chat_id, recent_limit + 2)
    recent_messages = await hydrate_legacy_forward_messages(
        recent_messages, runtime_api, settings
    )
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
        chronological_messages(recent_selected),
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
        quoted_block = trim(
            render_line(
                quoted_msg, sender_name=display_name(quoted_msg), settings=settings
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
        rendered = trim(
            render_line(message, sender_name=display_name(message), settings=settings),
            recent_chars + settings.context.forward_max_chars + 32,
        )
        recent_lines.append(rendered)
        context_ids.append(message_id)

    current_text = current_message_text(event, source_msg, settings, trigger_reason)
    current_sender = sender_name or display_name(source_msg)
    current_budget = max(1, total_chars - len(quoted_block))
    current_block = trim(
        render_line(
            source_msg,
            sender_name=current_sender,
            text_override=current_text,
            settings=settings,
        ),
        current_budget,
    )
    recent_block = trim_to_budget(
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
        context_ids=unique(context_ids),
        quoted_block=quoted_block,
        recent_block=recent_block,
        current_block=current_block[:total_chars],
        variant="group_topic_ai"
        if is_group and analysis
        else ("group_compact" if is_group else "private_contextual"),
        chat_type=chat_type,
        trigger_reason=trigger_reason,
        current_time=format_full_time(getattr(source_msg, "timestamp", None)),
        sender_name=current_sender,
        max_reply_chars=prompt_char_limit(settings, is_group),
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
        candidate_items.append(
            {
                "id": str(message.message_id),
                "sender_id": str(getattr(message, "user_id", "") or ""),
                "sender_name": display_name(message),
                "time": format_full_time(getattr(message, "timestamp", None)),
                "content": render_message(message, settings=settings),
                "reply_to_message_id": first_reply_id(message),
                "features": message_features(message),
                "forward_summary": render_forward_summary(message, settings),
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
