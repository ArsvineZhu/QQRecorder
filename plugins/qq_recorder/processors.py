"""Message processing pipeline: core message handling, forward parsing, image
processing."""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from .config import RecorderSettings
from .events import format_stored_log, is_command
from .forward_parser import flatten_forward_nodes, parse_forward_response
from .image_handler import process_images
from .message_parser import ImageInfo, parse_message
from .models import Image
from .storage import MessageStorage
from .text_utils import escape_text


class MessageProcessor:
    """Orchestrates the full message processing pipeline."""

    def __init__(
        self,
        storage: MessageStorage,
        settings: RecorderSettings,
        api,
        logger: Any,
    ):
        self.storage = storage
        self.settings = settings
        self.api = api
        self.logger = logger

    async def process_message(self, event: dict) -> int | None:
        """Process a single message event dict. Returns the DB id or None."""
        try:
            chat_type = event.get("message_type")
            if not chat_type:
                return None
            chat_id = (
                event.get("group_id") if chat_type == "group" else event.get("user_id")
            )
            if not chat_id:
                return None

            from .config import is_chat_monitored

            if not is_chat_monitored(chat_type, str(chat_id), self.settings):
                return None

            raw = event.get("raw_message", "")
            if is_command(raw, ("recorder", "/recorder", "r", "/r")):
                return None

            parsed = parse_message(event.get("message", []), raw)
            forward_messages = await self._process_forwards(parsed.forward_ids)

            message_data = {
                "message_id": event["message_id"],
                "user_id": event["user_id"],
                "group_id": event.get("group_id"),
                "chat_type": chat_type,
                "timestamp": datetime.fromtimestamp(event["time"]),
                "raw_message": escape_text(event.get("raw_message", "")),
                "segments": parsed.segments,
                "images": [
                    {
                        "file_url": img.file_url,
                        "file_unique": img.file_unique,
                        "file_size": img.file_size,
                        "is_sticker": img.is_sticker,
                        "sticker_confidence": img.sticker_confidence,
                    }
                    for img in parsed.images
                ],
                "replies": [
                    {"reply_to_message_id": rep.reply_to_message_id}
                    for rep in parsed.replies
                ],
                "forward_messages": forward_messages,
                "at_mentions": [
                    {"target_user_id": at.target_user_id} for at in parsed.at_mentions
                ],
            }

            message_db_id = await self.storage.save_message(message_data)

            self.logger.info(
                format_stored_log(
                    event, parsed, self.settings.forward.max_depth, message_db_id
                )
            )

            if parsed.images:
                await self._process_images(message_db_id, parsed.images)

            return message_db_id
        except Exception as e:
            self.logger.error("Error processing message: %s", e, exc_info=True)
            return None

    async def _process_forwards(self, forward_ids: list[str]) -> list[dict]:
        """Fetch and parse forward messages by their IDs."""
        if not self.settings.forward.parse_content:
            return [
                {"forward_id": fid, "depth": 0, "content_summary": ""}
                for fid in forward_ids
            ]
        all_forwards = []
        for forward_id in forward_ids:
            if not forward_id or not forward_id.strip():
                continue
            try:
                response = await self.api.qq.query.get_forward_msg(forward_id)
                nodes = parse_forward_response(
                    response, max_depth=self.settings.forward.max_depth
                )
                flattened = flatten_forward_nodes(nodes)
                all_forwards.extend(flattened)
            except Exception as e:
                self.logger.error("Forward parse failed for %s: %s", forward_id, e)
                all_forwards.append(
                    {"forward_id": forward_id, "depth": 0, "content_summary": ""}
                )
        return all_forwards

    async def _process_images(
        self, message_db_id: int, images_info: list[ImageInfo]
    ) -> None:
        """Download images and update DB records."""
        if not self.settings.image.download:
            return
        try:
            results = await process_images(
                images_info, self.settings.storage.images_dir, self.settings.image
            )
            for img_info, img_result in zip(images_info, results, strict=True):
                if img_result.success:
                    async with self.storage.AsyncSessionLocal() as session:  # pyright: ignore[reportOptionalCall]
                        stmt = select(Image).where(
                            Image.message_id == message_db_id,
                            Image.file_url == img_info.file_url,
                        )
                        db_result = await session.execute(stmt)
                        image = db_result.scalar_one_or_none()
                        if image:
                            image.local_path = img_result.local_path
                            image.file_unique = img_result.file_unique
                            image.downloaded = True
                            image.is_sticker = img_info.is_sticker
                            image.sticker_confidence = img_info.sticker_confidence
                            await session.commit()
                    self.logger.info(
                        "Image saved: %s (%d bytes)",
                        img_result.local_path,
                        img_result.file_size,
                    )
                else:
                    self.logger.warning(
                        "Image download failed [%s]: %s",
                        img_info.file_unique,
                        img_result.error,
                    )
        except Exception as e:
            self.logger.error("Image processing failed: %s", e, exc_info=True)
