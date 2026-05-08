import os
from typing import Optional, Dict
from datetime import datetime
from sqlalchemy import select
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from .config import RecorderSettings, DEFAULT_CONFIG, build_config, is_chat_monitored
from .models import Image
from .storage import MessageStorage
from .message_parser import parse_message, ImageInfo
from .image_handler import process_images, ImageResult
from .forward_parser import parse_forward_response, flatten_forward_nodes
from .text_utils import escape_text, unescape_text


class QQRecorderPlugin(NcatBotPlugin):
    name = "qq_recorder"
    version = "1.1.3"
    author = "Arsvine Zhu"
    description = "静默 QQ 消息记录器"

    def __init__(self):
        super().__init__()
        self._settings: RecorderSettings
        self.storage: MessageStorage

    async def on_load(self):
        self.init_defaults(DEFAULT_CONFIG)
        self._settings = build_config(self.config)

        db_path = self._settings.storage.database
        if not os.path.isabs(db_path):
            db_path = str(self.workspace / db_path)
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        images_dir = self._settings.storage.images_dir
        if not os.path.isabs(images_dir):
            images_dir = str(self.workspace / images_dir)
        os.makedirs(images_dir, exist_ok=True)
        self._settings.storage.images_dir = images_dir

        db_url = f"sqlite+aiosqlite:///{db_path}"
        self.storage = MessageStorage(db_url)
        await self.storage.init_db()

        self.logger.info(
            "QQRecorder loaded | monitor_all=%s | db=%s | images=%s",
            self._settings.monitor_all, db_path, images_dir,
        )

    COMMAND_PREFIXES = ("recorder", "/recorder", "r", "/r")

    @registrar.qq.on_group_command("recorder", "/recorder", "r", ignore_case=True)
    async def on_group_recorder(self, event: GroupMessageEvent):
        await self._handle_recorder(event)

    @registrar.on_private_command("recorder", "/recorder", "r", ignore_case=True)
    async def on_private_recorder(self, event: PrivateMessageEvent):
        await self._handle_recorder(event)

    async def _handle_recorder(self, event):
        raw = event.raw_message.strip()
        tokens = raw.split()
        if len(tokens) < 2:
            await event.reply(text="\nUsage: /recorder <stats|recent [N]|search <keyword>>")
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

    async def _handle_stats(self, event):
        chat_type = "group" if hasattr(event, "group_id") and event.group_id else "private"
        chat_id = str(event.group_id) if chat_type == "group" else str(event.user_id)

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

    async def _handle_recent(self, event, limit: int):
        chat_type = "group" if hasattr(event, "group_id") and event.group_id else "private"
        chat_id = str(event.group_id) if chat_type == "group" else str(event.user_id)

        messages = await self.storage.get_recent_messages(chat_type, chat_id, limit)
        if not messages:
            await event.reply(text="No messages recorded")
            return

        lines = [f"\nRecent {len(messages)} messages:"]
        for msg in messages:
            ts = msg.timestamp.strftime("%m-%d %H:%M") if msg.timestamp else "?"
            raw = unescape_text(msg.raw_message or "")
            if len(raw) > 30:
                raw = raw[:27] + "..."
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
            lines.append(f"  {ts} {raw}{extra_str}")

        await event.reply(text="\n".join(lines))

    async def _handle_search(self, event, keyword: str):
        chat_type = "group" if hasattr(event, "group_id") and event.group_id else "private"
        chat_id = str(event.group_id) if chat_type == "group" else str(event.user_id)

        messages = await self.storage.search_messages(keyword, chat_type, chat_id, limit=10)
        if not messages:
            await event.reply(text=f'No results for "{keyword}"')
            return

        lines = [f'\n"{keyword}" — {len(messages)} results:']
        for msg in messages:
            ts = msg.timestamp.strftime("%m-%d %H:%M") if msg.timestamp else "?"
            raw = unescape_text(msg.raw_message or "")
            if len(raw) > 30:
                raw = raw[:27] + "..."
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
            lines.append(f"  {ts} {raw}{extra_str}")

        await event.reply(text="\n".join(lines))

    async def on_close(self):
        if self.storage:
            await self.storage.close()
        self.logger.info("QQRecorder unloaded")

    @registrar.qq.on_group_message()
    async def on_group_message(self, event: GroupMessageEvent):
        event_dict = self._event_to_dict(event)
        await self._process_message(event_dict)

    @registrar.qq.on_private_message()
    async def on_private_message(self, event: PrivateMessageEvent):
        event_dict = self._event_to_dict(event)
        await self._process_message(event_dict)

    async def _process_message(self, event: Dict) -> Optional[int]:
        try:
            chat_type = event.get("message_type")
            if not chat_type:
                return None
            chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
            if not chat_id:
                return None
            if not is_chat_monitored(chat_type, str(chat_id), self._settings):
                return None

            raw = event.get("raw_message", "")
            if self._is_command(raw):
                return None

            parsed = parse_message(event.get("message", []))
            forward_messages = await self._process_forwards(parsed.forward_ids)

            message_data = {
                "message_id": event["message_id"],
                "user_id": event["user_id"],
                "group_id": event.get("group_id"),
                "chat_type": chat_type,
                "timestamp": datetime.fromtimestamp(event["time"]),
                "raw_message": escape_text(event.get("raw_message", "")),
                "segments": parsed.segments,
                "images": [{"file_url": img.file_url, "file_unique": img.file_unique, "file_size": img.file_size} for img in parsed.images],
                "replies": [{"reply_to_message_id": rep.reply_to_message_id} for rep in parsed.replies],
                "forward_messages": forward_messages,
                "at_mentions": [{"target_user_id": at.target_user_id} for at in parsed.at_mentions],
            }

            message_db_id = await self.storage.save_message(message_data)

            self._log_stored(event, parsed, message_db_id)

            if parsed.images:
                await self._process_images(message_db_id, parsed.images)

            return message_db_id
        except Exception as e:
            self.logger.error("Error processing message: %s", e, exc_info=True)
            return None

    async def _process_forwards(self, forward_ids: list[str]) -> list[dict]:
        if not self._settings.forward.parse_content:
            return [{"forward_id": fid, "depth": 0, "content_summary": ""} for fid in forward_ids]
        all_forwards = []
        for forward_id in forward_ids:
            try:
                response = await self.api.qq.query.get_forward_msg(forward_id)
                nodes = parse_forward_response(response, max_depth=self._settings.forward.max_depth)
                flattened = flatten_forward_nodes(nodes)
                all_forwards.extend(flattened)
            except Exception as e:
                self.logger.error("Forward parse failed for %s: %s", forward_id, e)
                all_forwards.append({"forward_id": forward_id, "depth": 0, "content_summary": ""})
        return all_forwards

    async def _process_images(self, message_db_id: int, images_info: list[ImageInfo]) -> None:
        if not self._settings.image.download:
            return
        try:
            results = await process_images(images_info, self._settings.storage.images_dir, self._settings.image)
            for img_info, img_result in zip(images_info, results):
                if img_result.success:
                    async with self.storage.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
                        stmt = select(Image).where(
                            Image.message_id == message_db_id,
                            Image.file_unique == img_info.file_unique,
                        )
                        db_result = await session.execute(stmt)
                        image = db_result.scalar_one_or_none()
                        if image:
                            image.local_path = img_result.local_path
                            image.downloaded = True
                            await session.commit()
                    self.logger.info("Image saved: %s (%d bytes)", img_result.local_path, img_result.file_size)
                else:
                    self.logger.warning("Image download failed [%s]: %s", img_info.file_unique, img_result.error)
        except Exception as e:
            self.logger.error("Image processing failed: %s", e, exc_info=True)

    def _event_to_dict(self, event) -> dict:
        message_segments = [seg.to_dict() for seg in event.message]

        # Type assertions to eliminate OptionalMemberAccess warnings
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
                "user_id": str(event.sender.user_id) if has_sender and hasattr(event.sender, "user_id") else "",
                "nickname": event.sender.nickname if has_sender and hasattr(event.sender, "nickname") else "",
                "card": str(event.sender.card) if has_sender and hasattr(event.sender, "card") and event.sender.card else "",
            },
        }

    def _log_stored(self, event: Dict, parsed, message_db_id: int) -> None:
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
            extras.append(f"fwd(depth={self._settings.forward.max_depth})")
        if parsed.at_mentions:
            extras.append(f"@{len(parsed.at_mentions)}")
        if extras:
            parts.append(f" [{','.join(extras)}]")
        parts.append(f" -> id#{message_db_id}")

        self.logger.info("".join(parts))

    def _is_command(self, raw_message: str) -> bool:
        if not raw_message:
            return False
        first_token = raw_message.strip().split()[0].lower()
        return first_token in self.COMMAND_PREFIXES
