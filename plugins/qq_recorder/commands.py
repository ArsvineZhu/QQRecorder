"""Command handling for QQRecorder: stats, recent, search."""

import logging
from typing import Any, Optional

from .storage import MessageStorage
from .text_utils import unescape_text


def get_chat_info(event) -> tuple[str, str]:
    """Extract (chat_type, chat_id) from an event."""
    chat_type = "group" if hasattr(event, "group_id") and event.group_id else "private"
    chat_id = str(event.group_id) if chat_type == "group" else str(event.user_id)
    return chat_type, chat_id


def format_message_brief(msg, max_len: int = 30) -> str:
    """Format a single message for brief display in recent/search results."""
    ts = msg.timestamp.strftime("%m-%d %H:%M") if msg.timestamp else "?"
    raw = unescape_text(msg.raw_message or "")
    if len(raw) > max_len:
        raw = raw[: max_len - 3] + "..."
    extras = []
    if msg.has_image:
        extras.append("img")
    if msg.has_reply:
        extras.append("reply")
    if msg.has_forward:
        extras.append("fwd")
    if msg.has_at:
        extras.append("@")
    extra_str = f" [{','.join(extras)}]" if extras else ""
    return f"  {ts} {raw}{extra_str}"


class CommandHandler:
    """Handles all /recorder subcommands."""

    def __init__(self, storage: MessageStorage, logger: Any):
        self.storage = storage
        self.logger = logger

    async def route(self, event) -> None:
        """Parse subcommand from event and dispatch to the right handler."""
        raw = event.raw_message.strip()
        tokens = raw.split()
        if len(tokens) < 2:
            await event.reply(
                text="\nUsage: /recorder <stats|recent [N]|search <keyword>>"
            )
            return

        subcmd = tokens[1].lower()
        if subcmd == "stats":
            await self._handle_stats(event)
        elif subcmd == "recent":
            count = 5
            if len(tokens) > 2:
                try:
                    count = int(tokens[2])
                except ValueError:
                    pass
            await self._handle_recent(event, min(count, 20))
        elif subcmd == "search":
            if len(tokens) < 3:
                await event.reply(text="\nUsage: /recorder search <keyword>")
                return
            keyword = " ".join(tokens[2:])
            await self._handle_search(event, keyword)
        else:
            await event.reply(text="\nUnknown subcommand. Use: stats, recent, search")

    async def _handle_stats(self, event) -> None:
        chat_type, chat_id = get_chat_info(event)

        total = await self.storage.count_messages(chat_type, chat_id)
        total_all = await self.storage.count_messages()
        img_total = await self.storage.count_images(chat_type, chat_id)
        img_downloaded = await self.storage.count_downloaded_images(chat_type, chat_id)

        label = "群" if chat_type == "group" else "聊"
        lines = [
            f"\nRecorder Stats",
            f"  本{label}: {total} msgs | {img_total} imgs ({img_downloaded} downloaded)",
            f"  Total: {total_all} msgs",
        ]
        await event.reply(text="\n".join(lines))

    async def _handle_recent(self, event, limit: int) -> None:
        chat_type, chat_id = get_chat_info(event)

        messages = await self.storage.get_recent_messages(chat_type, chat_id, limit)
        if not messages:
            await event.reply(text="No messages recorded")
            return

        lines = [f"\nRecent {len(messages)} messages:"]
        for msg in messages:
            lines.append(format_message_brief(msg))
        await event.reply(text="\n".join(lines))

    async def _handle_search(self, event, keyword: str) -> None:
        chat_type, chat_id = get_chat_info(event)

        messages = await self.storage.search_messages(
            keyword, chat_type, chat_id, limit=10
        )
        if not messages:
            await event.reply(text=f'No results for "{keyword}"')
            return

        lines = [f'\n"{keyword}" — {len(messages)} results:']
        for msg in messages:
            lines.append(format_message_brief(msg))
        await event.reply(text="\n".join(lines))
