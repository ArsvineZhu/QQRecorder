"""Pure utility functions for event conversion, command detection, and log
formatting."""

from .text_utils import unescape_text


def event_to_dict(event) -> dict:
    """Convert an NcatBot event object to a plain dict for internal processing.

    NcatBot event objects don't serialize cleanly, so we manually extract
    the fields we need.
    """
    message_segments = [seg.to_dict() for seg in event.message]

    has_group = hasattr(event, "group_id") and event.group_id
    if has_group:
        assert event.group_id is not None

    has_user = hasattr(event, "user_id")
    if has_user:
        assert event.user_id is not None

    has_sender = hasattr(event, "sender")
    if has_sender:
        assert event.sender is not None

    return {
        "post_type": "message",
        "message_type": "group" if has_group else "private",
        "message_id": str(event.message_id) if hasattr(event, "message_id") else "",
        "group_id": str(event.group_id) if has_group else None,
        "user_id": str(event.user_id) if has_user else "",
        "time": event.time if hasattr(event, "time") else 0,
        "message": message_segments,
        "raw_message": event.raw_message if hasattr(event, "raw_message") else "",
        "sender": {
            "user_id": str(event.sender.user_id)
            if has_sender and hasattr(event.sender, "user_id")
            else "",
            "nickname": event.sender.nickname
            if has_sender and hasattr(event.sender, "nickname")
            else "",
            "card": str(event.sender.card)
            if has_sender and hasattr(event.sender, "card") and event.sender.card
            else "",
        },
    }


def is_command(raw_message: str, prefixes: tuple[str, ...]) -> bool:
    """Check if a raw message starts with a command prefix."""
    if not raw_message:
        return False
    first_token = raw_message.strip().split()[0].lower()
    return first_token in prefixes


def format_stored_log(event: dict, parsed, max_depth: int, message_db_id: int) -> str:
    """Format a log line for a stored message."""
    chat_type = event.get("message_type")
    chat_id = event.get("group_id") or event.get("user_id")
    sender = event.get("sender", {})
    nickname = sender.get("nickname", "")
    card = sender.get("card", "")
    display_name = card or nickname or event.get("user_id", "?")
    raw = unescape_text(event.get("raw_message", ""))
    if len(raw) > 50:
        raw = raw[:47] + "..."

    parts = [f"[{chat_type}:{chat_id}] <{display_name}> {raw}"]
    extras = []
    if parsed.images:
        extras.append(f"{len(parsed.images)}img")
    if parsed.replies:
        extras.append("reply")
    if parsed.forward_ids:
        extras.append(f"fwd(depth={max_depth})")
    if parsed.at_mentions:
        extras.append(f"@{len(parsed.at_mentions)}")
    if extras:
        parts.append(f" [{','.join(extras)}]")
    parts.append(f" -> id#{message_db_id}")

    return "".join(parts)
