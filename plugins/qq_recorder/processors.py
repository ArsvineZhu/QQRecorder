"""Message processing pipeline: core message handling, forward parsing, image
processing."""

import asyncio
import os
from datetime import datetime
from typing import Any

from .config import RecorderSettings
from .events import format_stored_log, is_command
from .forward_parser import flatten_forward_nodes, parse_forward_response
from .image_handler import process_images
from .message_parser import ImageInfo, parse_message
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
        self._inflight_semaphore = asyncio.Semaphore(settings.processing.max_inflight)
        self._image_download_semaphore = asyncio.Semaphore(
            settings.processing.image_download_concurrency
        )

    async def process_message(self, event: dict) -> int | None:
        """Process a single message event dict. Returns the DB id or None."""
        async with self._inflight_semaphore:
            try:
                chat_type = event.get("message_type")
                if not chat_type:
                    return None
                chat_id = (
                    event.get("group_id")
                    if chat_type == "group"
                    else event.get("user_id")
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
                    "sender_nickname": event.get("sender", {}).get("nickname", ""),
                    "sender_card": event.get("sender", {}).get("card", ""),
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
                        {"target_user_id": at.target_user_id}
                        for at in parsed.at_mentions
                    ],
                    "app_shares": [
                        {
                            "app_name": share.app_name,
                            "title": share.title,
                            "description": share.description,
                            "url": share.url,
                            "prompt": share.prompt,
                            "raw_data": share.raw_data,
                        }
                        for share in parsed.app_shares
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
                self.logger.warning("Forward parse failed for %s: %s", forward_id, e)
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
            pending_images: list[ImageInfo] = []
            for img_info in images_info:
                if not img_info.file_url:
                    pending_images.append(img_info)
                    continue

                cached = await self.storage.find_reusable_image_by_url(
                    img_info.file_url
                )
                if cached and cached.local_path and os.path.exists(cached.local_path):
                    await self.storage.apply_cached_image_to_message(
                        message_db_id=message_db_id,
                        file_url=img_info.file_url,
                        local_path=cached.local_path,
                        file_unique=cached.file_unique,
                        file_size=cached.file_size,
                        is_sticker=img_info.is_sticker,
                        sticker_confidence=img_info.sticker_confidence,
                    )
                    self.logger.info("Image reused: %s", cached.local_path)
                    continue
                pending_images.append(img_info)

            if not pending_images:
                return

            results = await process_images(
                pending_images,
                self.settings.storage.images_dir,
                self.settings.image,
                download_semaphore=self._image_download_semaphore,
            )
            for img_info, img_result in zip(pending_images, results, strict=True):
                if img_result.success:
                    await self.storage.apply_cached_image_to_message(
                        message_db_id=message_db_id,
                        file_url=img_info.file_url,
                        local_path=img_result.local_path,
                        file_unique=img_result.file_unique,
                        file_size=img_result.file_size,
                        is_sticker=img_info.is_sticker,
                        sticker_confidence=img_info.sticker_confidence,
                    )
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
