from typing import Any

from ..config import ReplyPluginSettings
from ..llm.topic_analyzer import TopicAnalysis, analyze_topic, validate_topic_analysis
from .legacy_forward import (
    hydrate_legacy_forward_message,
    hydrate_legacy_forward_messages,
)
from .render import (
    chronological_messages,
    current_message_text,
    display_name,
    first_reply_id,
    format_full_time,
    message_features,
    render_forward_summary,
    render_line,
    render_message,
    trim,
    trim_to_budget,
    unique,
)
from .types import BuiltContext, TopicContextError


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
    visual_context: str = "",
) -> BuiltContext:
    if settings.context.mode == "topic_ai":
        return await _build_local_topic_context(
            source_msg,
            bridge,
            settings,
            event=event,
            trigger_reason=trigger_reason,
            sender_name=sender_name,
            runtime_api=runtime_api,
            visual_context=visual_context,
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
        visual_context=visual_context,
    )


async def expand_context(
    source_msg,
    local_ctx: BuiltContext,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event=None,
    trigger_reason: str = "",
    sender_name: str | None = None,
    analyzer_api=None,
    runtime_api=None,
    request_reason: str = "",
) -> BuiltContext:
    if analyzer_api is None or not settings.topic_analyzer.enabled:
        raise TopicContextError(TopicAnalysis(error_code="topic_analyzer_unavailable"))

    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
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
    quote_chain_depth = (
        settings.context.quote_chain_max_depth_group
        if is_group
        else settings.context.quote_chain_max_depth_private
    )

    source_msg = await hydrate_legacy_forward_message(source_msg, runtime_api, settings)
    assert source_msg is not None

    candidates = await bridge.get_candidates(
        chat_type,
        chat_id,
        limit=candidate_limit,
        since_minutes=since_minutes,
        before_or_at=getattr(source_msg, "timestamp", None),
    )
    candidates = await hydrate_legacy_forward_messages(
        candidates, runtime_api, settings
    )
    candidate_by_id = {str(message.message_id): message for message in candidates}
    current_id = str(source_msg.message_id)
    candidate_by_id[current_id] = source_msg

    for message_id in local_ctx.context_ids:
        if message_id in candidate_by_id:
            continue
        message = await bridge.get_message(message_id)
        if message is None:
            continue
        message = await hydrate_legacy_forward_message(message, runtime_api, settings)
        candidate_by_id[message_id] = message

    reply_chain = await bridge.get_reply_chain(source_msg, max_depth=quote_chain_depth)
    reply_chain = await hydrate_legacy_forward_messages(
        reply_chain, runtime_api, settings
    )
    for message in reply_chain:
        candidate_by_id[str(message.message_id)] = message

    reply_to_id = first_reply_id(source_msg)
    current_text = current_message_text(event, source_msg, settings, trigger_reason)
    analysis = await analyze_topic(
        analyzer_api,
        payload=_topic_payload(
            source_msg,
            list(candidate_by_id.values()),
            settings,
            current_text=current_text,
            current_sender=sender_name or display_name(source_msg),
            reply_to_id=reply_to_id,
            max_selected=max_selected,
            anchor_message_ids=local_ctx.context_ids,
            quote_chain_ids=[str(message.message_id) for message in reply_chain],
            request_reason=request_reason,
        ),
        settings=settings,
    )
    analysis = validate_topic_analysis(
        analysis,
        candidate_ids=set(candidate_by_id),
        current_message_id=current_id,
        min_confidence=settings.topic_analyzer.min_confidence,
    )
    analysis.candidate_count = len(candidate_by_id)
    if analysis.error_code:
        raise TopicContextError(analysis)

    context_ids = _merge_expanded_ids(
        local_ctx.context_ids, analysis.selected_message_ids
    )
    quote_chain_ids = {str(item.message_id) for item in reply_chain}
    recent_messages = chronological_messages(
        [
            candidate_by_id[message_id]
            for message_id in context_ids
            if message_id in candidate_by_id
            and message_id != current_id
            and message_id not in quote_chain_ids
        ]
    )
    return _assemble_context(
        source_msg,
        quoted_messages=reply_chain,
        recent_messages=recent_messages,
        settings=settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        analysis=analysis,
        context_id_order=context_ids,
        variant_override="group_topic_expanded"
        if is_group
        else "private_topic_expanded",
        visual_context=local_ctx.visual_context,
    )


async def _build_local_topic_context(
    source_msg,
    bridge,
    settings: ReplyPluginSettings,
    *,
    event,
    trigger_reason: str,
    sender_name: str | None,
    runtime_api,
    visual_context: str = "",
) -> BuiltContext:
    source_msg = await hydrate_legacy_forward_message(source_msg, runtime_api, settings)
    assert source_msg is not None

    chat_type = str(source_msg.chat_type)
    is_group = chat_type == "group"
    chat_id = str(source_msg.group_id if is_group else source_msg.user_id)
    recent_limit = (
        settings.context.local_recent_limit_group
        if is_group
        else settings.context.local_recent_limit_private
    )
    recent_window_minutes = (
        settings.context.local_recent_time_window_minutes_group
        if is_group
        else settings.context.local_recent_time_window_minutes_private
    )
    quote_chain_depth = (
        settings.context.quote_chain_max_depth_group
        if is_group
        else settings.context.quote_chain_max_depth_private
    )
    neighbor_limit = (
        settings.context.quote_neighbor_limit_group
        if is_group
        else settings.context.quote_neighbor_limit_private
    )

    reply_chain = await bridge.get_reply_chain(source_msg, max_depth=quote_chain_depth)
    reply_chain = await hydrate_legacy_forward_messages(
        reply_chain, runtime_api, settings
    )
    recent_messages = await bridge.get_recent_window(
        chat_type,
        chat_id,
        limit=recent_limit,
        since_minutes=recent_window_minutes,
        before_or_at=getattr(source_msg, "timestamp", None),
    )
    recent_messages = await hydrate_legacy_forward_messages(
        recent_messages, runtime_api, settings
    )

    neighbor_messages: list[Any] = []
    for quoted_message in reply_chain:
        items = await bridge.get_neighbors(
            chat_type,
            chat_id,
            anchor=quoted_message,
            before_limit=neighbor_limit,
            after_limit=neighbor_limit,
        )
        neighbor_messages.extend(items)
    neighbor_messages = await hydrate_legacy_forward_messages(
        neighbor_messages, runtime_api, settings
    )

    chain_id_order = [str(message.message_id) for message in reply_chain]
    chain_ids = set(chain_id_order)
    recent_selected: list[Any] = []
    for message in chronological_messages(recent_messages + neighbor_messages):
        message_id = str(message.message_id)
        if message_id == str(source_msg.message_id) or message_id in chain_ids:
            continue
        recent_selected.append(message)

    context_ids = unique(
        [str(source_msg.message_id), *chain_id_order]
        + [str(message.message_id) for message in recent_selected]
    )
    return _assemble_context(
        source_msg,
        quoted_messages=reply_chain,
        recent_messages=recent_selected,
        settings=settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        analysis=None,
        context_id_order=context_ids,
        variant_override="group_topic_local" if is_group else "private_topic_local",
        visual_context=visual_context,
    )


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
    visual_context: str = "",
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
        quoted_messages=[quoted_msg] if quoted_msg is not None else [],
        recent_messages=chronological_messages(recent_selected),
        settings=settings,
        event=event,
        trigger_reason=trigger_reason,
        sender_name=sender_name,
        analysis=None,
        context_id_order=None,
        variant_override=None,
        visual_context=visual_context,
    )


def _assemble_context(
    source_msg,
    *,
    quoted_messages: list[Any],
    recent_messages: list[Any],
    settings: ReplyPluginSettings,
    event,
    trigger_reason: str,
    sender_name: str | None,
    analysis: TopicAnalysis | None,
    context_id_order: list[str] | None,
    variant_override: str | None,
    visual_context: str = "",
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

    quoted_lines = [
        render_line(message, sender_name=display_name(message), settings=settings)
        for message in quoted_messages
        if message is not None
    ]
    quoted_block = trim_to_budget("\n".join(quoted_lines), quote_chars)

    quoted_ids = {
        str(message.message_id) for message in quoted_messages if message is not None
    }
    recent_lines: list[str] = []
    recent_ids: list[str] = []
    for message in chronological_messages(recent_messages):
        message_id = str(message.message_id)
        if message_id == str(source_msg.message_id) or message_id in quoted_ids:
            continue
        rendered = trim(
            render_line(message, sender_name=display_name(message), settings=settings),
            recent_chars + settings.context.forward_max_chars + 32,
        )
        recent_lines.append(rendered)
        recent_ids.append(message_id)

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

    context_ids = context_id_order or unique(
        [str(source_msg.message_id)]
        + [
            str(message.message_id)
            for message in quoted_messages
            if message is not None
        ]
        + recent_ids
    )
    variant = variant_override or (
        "group_topic_expanded"
        if is_group and analysis
        else ("group_compact" if is_group else "private_contextual")
    )
    return BuiltContext(
        context_ids=context_ids,
        quoted_block=quoted_block,
        recent_block=recent_block,
        current_block=current_block[:total_chars],
        variant=variant,
        chat_type=chat_type,
        trigger_reason=trigger_reason,
        current_time=format_full_time(getattr(source_msg, "timestamp", None)),
        sender_name=current_sender,
        topic_title=analysis.topic_title if analysis else "",
        topic_summary=analysis.topic_summary if analysis else "",
        topic_participants=participants,
        topic_confidence=analysis.confidence if analysis else 0.0,
        topic_candidate_count=analysis.candidate_count if analysis else 0,
        topic_error_code=analysis.error_code if analysis else "",
        topic_fallback_used=analysis.fallback_used if analysis else False,
        topic_excluded_ids_json=analysis.excluded_ids_json() if analysis else "[]",
        visual_context=visual_context,
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
    anchor_message_ids: list[str],
    quote_chain_ids: list[str],
    request_reason: str,
) -> dict[str, Any]:
    candidate_items = []
    for message in chronological_messages(candidates):
        message_id = str(message.message_id)
        candidate_items.append(
            {
                "id": message_id,
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
        "anchor_message_ids": anchor_message_ids,
        "quote_chain_message_ids": quote_chain_ids,
        "request_reason": request_reason,
    }


def _merge_expanded_ids(local_ids: list[str], selected_ids: list[str]) -> list[str]:
    return unique(local_ids + [str(item) for item in selected_ids])
