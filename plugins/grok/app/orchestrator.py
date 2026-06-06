from __future__ import annotations

import hashlib
import json
import logging
import time

from ..delivery import SendOutcome, send_reply
from ..profile_defaults import build_default_profile
from ..shared.conversation_history import to_persisted_transcript
from ..trigger import final_decision, prefilter_event

logger = logging.getLogger("grok.orchestrator")


async def handle_event(plugin, event, chat_type: str) -> None:  # noqa: C901
    del chat_type
    prefilter_reason = prefilter_event(event, plugin.settings)
    if prefilter_reason is None and not plugin.settings.trigger.allow_reply_to_bot:
        logger.debug("handle: prefilter rejected, no reply-to-bot fallback")
        return

    bridge = plugin._bridge
    trace_store = plugin._trace_store
    if bridge is None or trace_store is None or plugin._runtime is None:
        logger.warning("handle: bridge/trace/runtime not initialized")
        return

    started_at = time.perf_counter()
    message_id = str(getattr(event, "message_id", "") or "")
    source_msg = await bridge.wait_until_visible(
        message_id,
        timeout_ms=plugin.settings.read_after_write.timeout_ms,
        backoff_ms=plugin.settings.read_after_write.backoff_ms,
    )
    if source_msg is None:
        logger.info("handle: message not visible after wait id=%s", message_id)
        return

    bot_reply_message_ids = await trace_store.get_sent_message_ids(
        "group" if getattr(event, "group_id", None) is not None else "private",
        str(getattr(event, "group_id", None) or getattr(event, "user_id", "") or ""),
    )
    allowed, decision_reason = final_decision(
        event,
        source_msg=source_msg,
        prefilter_reason=prefilter_reason,
        settings=plugin.settings,
        cooldowns=plugin._cooldowns,
        bot_reply_message_ids=bot_reply_message_ids,
    )
    if not allowed:
        logger.debug("handle: final decision denied reason=%s", decision_reason)
        return

    chat_id_str = str(
        getattr(source_msg, "group_id", None)
        or getattr(source_msg, "user_id", "")
        or ""
    )
    user_id_str = str(getattr(source_msg, "user_id", "") or "")

    logger.info(
        "handle: start chat=%s user=%s reason=%s",
        chat_id_str,
        user_id_str,
        decision_reason,
    )

    trace_id = await trace_store.insert_trace(
        source_message_id=message_id,
        chat_type=str(getattr(source_msg, "chat_type", "") or ""),
        chat_id=chat_id_str,
        user_id=user_id_str,
        decision_seed=_decision_seed(event),
        trigger_reason=decision_reason,
        parser_version="qq_recorder:v1",
        context_version="grok_context:v1",
        profile_version="grok_profile:v1",
        working_context_json="{}",
    )

    # Automatically create a blank profile for new users
    profile_store = getattr(plugin, "_profile_json_store", None)
    if profile_store is not None:
        existing = await profile_store.get_profile(user_id_str)
        if existing is None:
            record = build_default_profile(
                user_id=user_id_str,
                chat_type=str(getattr(source_msg, "chat_type", "") or ""),
                chat_id=chat_id_str,
                sender_nickname=str(getattr(source_msg, "sender_nickname", "") or ""),
                sender_card=str(getattr(source_msg, "sender_card", "") or ""),
            )
            await profile_store.upsert_profile(user_id_str, record)
            logger.info(
                "handle: auto-created profile user=%s",
                user_id_str,
            )

    outcome = await plugin._runtime.run(
        event=event,
        source_msg=source_msg,
        trigger_reason=decision_reason,
    )

    working = outcome.working_context
    await trace_store.finish_working_context(
        trace_id,
        json.dumps(
            {
                "current_message": working.context.current_message,
                "chat_type": working.context.chat_type,
                "chat_id": working.context.chat_id,
                "user_id": working.context.user_id,
                "parser_version": working.context.parser_version,
                "context_version": working.context.context_version,
                "profile_version": working.context.profile_version,
                "evidence": [
                    {"kind": b.kind, "label": b.label, "content": b.content}
                    for b in working.evidence
                ],
                "termination_reason": outcome.termination_reason,
            },
            ensure_ascii=False,
        ),
    )
    for step in outcome.steps:
        await trace_store.add_step(trace_id, step)

    send_outcome = SendOutcome(False, None, 0, None)
    if outcome.text:
        send_outcome = await send_reply(
            plugin.api, event, outcome.text, plugin.settings
        )

    conversation_store = getattr(plugin, "_conversation_store", None)
    if (
        conversation_store is not None
        and send_outcome.sent
        and outcome.text
        and outcome.messages_history
    ):
        agent_settings = getattr(plugin.settings, "agent", None)
        await conversation_store.upsert_session(
            str(getattr(source_msg, "chat_type", "") or ""),
            chat_id_str,
            to_persisted_transcript(
                outcome.messages_history,
                max_messages=int(
                    getattr(agent_settings, "conversation_history_max_messages", 20)
                    or 20
                ),
            ),
        )

    await trace_store.finish_trace(
        trace_id,
        model_name=outcome.model_name,
        response_text=outcome.text,
        error_code=outcome.error_code or send_outcome.error_code,
        sent=send_outcome.sent,
        sent_message_id=send_outcome.sent_message_id,
        sent_parts=send_outcome.sent_parts,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
    )

    latency = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "handle: done id=%s chat=%s latency=%dms error=%s",
        message_id,
        chat_id_str,
        latency,
        outcome.error_code or send_outcome.error_code or "none",
    )


def _decision_seed(event) -> str:
    key = f"{getattr(event, 'message_id', '')}:{getattr(event, 'time', '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
