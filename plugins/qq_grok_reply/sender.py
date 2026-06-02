from dataclasses import dataclass

from ncatbot.types import MessageArray

from .text_splitter import split_text


@dataclass
class SendOutcome:
    sent: bool
    sent_message_id: str | None
    sent_parts: int
    error_code: str | None


async def send_reply(api, event, text: str, settings) -> SendOutcome:
    is_group = getattr(event, "group_id", None) is not None
    max_chars = (
        settings.send.group_max_chars_per_part
        if is_group
        else settings.send.private_max_chars_per_part
    )
    max_parts = (
        settings.send.group_max_parts if is_group else settings.send.private_max_parts
    )
    parts = split_text(text, max_chars=max_chars, max_parts=max_parts)
    sent_message_id: str | None = None
    sent_parts = 0

    for index, part in enumerate(parts):
        try:
            payload = _build_payload(
                event, part, settings, is_group=is_group, is_first=index == 0
            )
            if is_group:
                result = await api.qq.send_group_msg(str(event.group_id), payload)
            else:
                result = await api.qq.send_private_msg(str(event.user_id), payload)
            sent_parts += 1
            if sent_message_id is None:
                sent_message_id = str(getattr(result, "message_id", "") or "") or None
        except Exception:
            return SendOutcome(
                sent=False,
                sent_message_id=sent_message_id,
                sent_parts=sent_parts,
                error_code="partial_send" if sent_parts > 0 else "send_error",
            )

    return SendOutcome(
        sent=True,
        sent_message_id=sent_message_id,
        sent_parts=sent_parts,
        error_code=None,
    )


def _build_payload(event, text: str, settings, *, is_group: bool, is_first: bool):
    msg = MessageArray()
    if is_group and is_first and settings.send.group_use_reply_segment:
        msg.add_reply(str(event.message_id))
    if is_group and is_first and settings.send.group_at_sender:
        msg.add_at(str(event.user_id))
    msg.add_text(text)
    return msg.to_list()
