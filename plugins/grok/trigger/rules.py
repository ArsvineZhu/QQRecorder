import logging
import time
from typing import Any

from ..config import RECORDER_COMMAND_PREFIXES, is_chat_targeted

try:
    from ncatbot.types import Reply as MessageReply
except Exception:  # pragma: no cover
    MessageReply = None

logger = logging.getLogger("grok.trigger")


class CooldownTracker:
    def __init__(self) -> None:
        self._next_allowed_at: dict[str, float] = {}

    def allow(self, source_msg, settings) -> bool:
        now = time.monotonic()
        keys_with_delay: list[tuple[str, float]] = []
        if str(getattr(source_msg, "chat_type", "")) == "group":
            chat_id = str(getattr(source_msg, "group_id", "") or "")
            keys_with_delay.append((f"group-chat:{chat_id}", 2.0))
            keys_with_delay.append(
                (f"group-user:{chat_id}:{getattr(source_msg, 'user_id', '')}", 5.0)
            )
        else:
            keys_with_delay.append(
                (f"private-user:{getattr(source_msg, 'user_id', '')}", 1.0)
            )

        if any(now < self._next_allowed_at.get(key, 0.0) for key, _ in keys_with_delay):
            return False

        for key, delay in keys_with_delay:
            self._next_allowed_at[key] = now + delay
        return True


def prefilter_event(event, settings) -> str | None:
    if not settings.enabled:
        logger.debug("prefilter: plugin disabled")
        return None

    user_id = str(getattr(event, "user_id", "") or "")
    self_id = str(getattr(event, "self_id", "") or "")
    if settings.trigger.ignore_self and user_id and self_id and user_id == self_id:
        logger.debug("prefilter: ignored self message")
        return None

    chat_type = "group" if getattr(event, "group_id", None) else "private"
    chat_id = str(
        getattr(event, "group_id", None) or getattr(event, "user_id", "") or ""
    )
    if not chat_id or not is_chat_targeted(chat_type, chat_id, settings):
        logger.debug("prefilter: chat not targeted type=%s id=%s", chat_type, chat_id)
        return None

    raw_message = str(getattr(event, "raw_message", "") or "").strip()
    if settings.trigger.ignore_recorder_command and _is_recorder_command(raw_message):
        logger.debug("prefilter: ignored recorder command")
        return None

    if chat_type == "private":
        if settings.trigger.private_enabled:
            logger.info("trigger: private message from %s", user_id)
            return "private_default"
        return None

    if not settings.trigger.group_enabled:
        logger.debug("prefilter: group trigger disabled")
        return None

    prefix = _matched_prefix(raw_message, settings.trigger.prefixes)
    if prefix is not None:
        logger.info("trigger: prefix match prefix=%s user=%s", prefix, user_id)
        return f"prefix:{prefix}"

    if settings.trigger.allow_at and _is_at_bot(
        getattr(event, "message", None),
        self_id,
    ):
        logger.info("trigger: @bot mention user=%s", user_id)
        return "group_at_bot"

    logger.debug("prefilter: no trigger matched raw=%s", raw_message[:60])
    return None


def final_decision(
    event,
    source_msg,
    prefilter_reason: str | None,
    settings,
    cooldowns: CooldownTracker,
    bot_reply_message_ids: set[str] | None = None,
) -> tuple[bool, str]:
    if source_msg is None:
        logger.info("trigger: denied missing_recorder_row")
        return False, "missing_recorder_row"

    reason = prefilter_reason
    if reason is None and settings.trigger.allow_reply_to_bot:
        reply_ids = _extract_reply_ids(getattr(event, "message", None))
        if bot_reply_message_ids and reply_ids & bot_reply_message_ids:
            reason = "reply_to_bot"

    if reason is None:
        logger.debug("trigger: denied no_trigger")
        return False, "no_trigger"
    if not cooldowns.allow(source_msg, settings):
        logger.debug("trigger: denied cooldown")
        return False, "cooldown"

    logger.info("trigger: allowed reason=%s", reason)
    return True, reason


def _is_recorder_command(raw_message: str) -> bool:
    if not raw_message:
        return False
    return raw_message.split()[0].lower() in RECORDER_COMMAND_PREFIXES


def _matched_prefix(raw_message: str, prefixes: list[str]) -> str | None:
    if not raw_message:
        return None
    first_token = raw_message.split()[0].lower()
    for value in prefixes:
        if first_token == value.lower():
            return value
    return None


def _is_at_bot(message, self_id: str) -> bool:
    if message is None or not self_id:
        return False
    if hasattr(message, "is_at"):
        try:
            return bool(message.is_at(self_id))
        except Exception:
            return False
    return False


def _extract_reply_ids(message) -> set[str]:
    if message is None or not hasattr(message, "filter"):
        return set()
    try:
        reply_type: Any = MessageReply
        if reply_type is None:
            return set()
        return {
            str(item.id)
            for item in message.filter(reply_type)
            if getattr(item, "id", None)
        }
    except Exception:
        return set()
