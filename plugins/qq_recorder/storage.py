import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy import desc, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from .config import LockRetryConfig
from .models import (
    AppShare,
    AtMention,
    Base,
    ForwardMessage,
    Image,
    ImageAnalysis,
    Message,
    MessageSegment,
    MonitoredChat,
    Reply,
    init_engine,
)

T = TypeVar("T")


class MessageStorage:
    def __init__(
        self,
        db_path: str,
        lock_retry: LockRetryConfig | None = None,
        sqlite_timeout: int = 10,
        logger: Any | None = None,
    ):
        self.db_path = db_path
        self.engine = None
        self.AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None
        self.lock_retry = lock_retry or LockRetryConfig()
        self.sqlite_timeout = sqlite_timeout
        self.logger = logger

    async def init_db(self):
        self.engine, self.AsyncSessionLocal = await init_engine(
            self.db_path, sqlite_timeout=self.sqlite_timeout
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(_ensure_message_sender_columns)
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        if self.engine:
            await self.engine.dispose()

    def _session(self) -> AsyncSession:
        """Return AsyncSessionLocal with assertion that init_db() was called."""
        assert self.AsyncSessionLocal is not None, "init_db() not called"
        return self.AsyncSessionLocal()

    @staticmethod
    def _is_locked_error(exc: OperationalError) -> bool:
        error_text = str(exc).lower()
        if (
            "database is locked" in error_text
            or "database table is locked" in error_text
        ):
            return True
        if isinstance(exc.orig, sqlite3.OperationalError):
            orig_text = str(exc.orig).lower()
            return (
                "database is locked" in orig_text
                or "database table is locked" in orig_text
            )
        return False

    async def _run_with_lock_retry(
        self,
        op_name: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        max_retries = self.lock_retry.max_retries
        for attempt in range(max_retries + 1):
            try:
                return await operation()
            except OperationalError as exc:
                if (
                    not self.lock_retry.enabled
                    or not self._is_locked_error(exc)
                    or attempt >= max_retries
                ):
                    raise
                delay_ms = self.lock_retry.base_delay_ms * (2**attempt)
                if self.logger:
                    self.logger.warning(
                        "Retrying DB operation %s after lock conflict "
                        "(attempt %d/%d, delay_ms=%d)",
                        op_name,
                        attempt + 1,
                        max_retries,
                        delay_ms,
                    )
                await asyncio.sleep(delay_ms / 1000)
        raise RuntimeError(f"unreachable lock retry path for {op_name}")

    async def save_message(self, message_data: dict) -> int:  # noqa: C901
        async def _save_once() -> int:
            async with self._session() as session:
                try:
                    message = Message(
                        message_id=message_data["message_id"],
                        user_id=message_data["user_id"],
                        sender_nickname=message_data.get("sender_nickname"),
                        sender_card=message_data.get("sender_card"),
                        group_id=message_data["group_id"],
                        chat_type=message_data["chat_type"],
                        timestamp=message_data["timestamp"],
                        raw_message=message_data["raw_message"],
                        has_image=len(message_data.get("images", [])) > 0,
                        has_reply=len(message_data.get("replies", [])) > 0,
                        has_forward=len(message_data.get("forward_messages", [])) > 0,
                        has_at=len(message_data.get("at_mentions", [])) > 0,
                        has_app_share=len(message_data.get("app_shares", [])) > 0,
                    )
                    session.add(message)
                    await session.flush()

                    for seg in message_data.get("segments", []):
                        segment = MessageSegment(
                            message_id=message.id,
                            segment_type=seg["segment_type"],
                            segment_order=seg["segment_order"],
                            segment_data=seg["segment_data"],
                        )
                        session.add(segment)

                    for img in message_data.get("images", []):
                        image = Image(
                            message_id=message.id,
                            file_url=img.get("file_url"),
                            file_unique=img.get("file_unique"),
                            file_size=img.get("file_size"),
                            local_path=img.get("local_path"),
                            width=img.get("width"),
                            height=img.get("height"),
                            downloaded=img.get("downloaded", False),
                        )
                        session.add(image)

                    for reply in message_data.get("replies", []):
                        reply_obj = Reply(
                            message_id=message.id,
                            reply_to_message_id=reply["reply_to_message_id"],
                        )
                        session.add(reply_obj)

                    async def save_forward(forward_data, parent_id=None):
                        forward = ForwardMessage(
                            message_id=message.id,
                            parent_forward_id=parent_id,
                            user_id=forward_data.get("user_id"),
                            nickname=forward_data.get("nickname"),
                            depth=forward_data.get("depth", 0),
                            content_summary=forward_data.get("content_summary"),
                            forward_id=forward_data.get("forward_id"),
                        )
                        session.add(forward)
                        await session.flush()
                        for child in forward_data.get("children", []):
                            await save_forward(child, forward.id)

                    for forward in message_data.get("forward_messages", []):
                        await save_forward(forward)

                    for at in message_data.get("at_mentions", []):
                        at_obj = AtMention(
                            message_id=message.id, target_user_id=at["target_user_id"]
                        )
                        session.add(at_obj)

                    for share in message_data.get("app_shares", []):
                        share_obj = AppShare(
                            message_id=message.id,
                            app_name=share.get("app_name", ""),
                            title=share.get("title", ""),
                            description=share.get("description", ""),
                            url=share.get("url", ""),
                            prompt=share.get("prompt", ""),
                            raw_data=share.get("raw_data", ""),
                        )
                        session.add(share_obj)

                    await session.commit()
                    return message.id
                except Exception:
                    await session.rollback()
                    raise

        return await self._run_with_lock_retry("save_message", _save_once)

    async def get_message(self, message_id: str) -> Message | None:
        async with self._session() as session:
            stmt = (
                select(Message)
                .where(Message.message_id == message_id)
                .options(
                    selectinload(Message.segments),
                    selectinload(Message.images),
                    selectinload(Message.replies),
                    selectinload(Message.forward_messages).options(
                        selectinload(ForwardMessage.children)
                    ),
                    selectinload(Message.at_mentions),
                    selectinload(Message.app_shares),
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_recent_messages(
        self, chat_type: str | None = None, chat_id: str | None = None, limit: int = 10
    ) -> list[Message]:
        async with self._session() as session:
            stmt = (
                select(Message)
                .options(
                    selectinload(Message.images),
                    selectinload(Message.at_mentions),
                    selectinload(Message.app_shares),
                )
                .order_by(desc(Message.timestamp))
            )
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def count_messages(
        self, chat_type: str | None = None, chat_id: str | None = None
    ) -> int:
        async with self._session() as session:
            stmt = select(func.count(Message.id))
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def count_images(
        self, chat_type: str | None = None, chat_id: str | None = None
    ) -> int:
        async with self._session() as session:
            stmt = select(func.count(Image.id)).join(
                Message, Image.message_id == Message.id
            )
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def count_downloaded_images(
        self, chat_type: str | None = None, chat_id: str | None = None
    ) -> int:
        async with self._session() as session:
            stmt = (
                select(func.count(Image.id))
                .join(Message, Image.message_id == Message.id)
                .where(Image.downloaded)
            )
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def count_stickers(
        self, chat_type: str | None = None, chat_id: str | None = None
    ) -> int:
        async with self._session() as session:
            stmt = (
                select(func.count(Image.id))
                .join(Message, Image.message_id == Message.id)
                .where(Image.is_sticker)
            )
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def search_messages(
        self,
        keyword: str,
        chat_type: str | None = None,
        chat_id: str | None = None,
        limit: int = 10,
    ) -> list[Message]:
        async with self._session() as session:
            stmt = (
                select(Message)
                .options(
                    selectinload(Message.images),
                    selectinload(Message.at_mentions),
                    selectinload(Message.app_shares),
                )
                .where(Message.raw_message.contains(keyword))
                .order_by(desc(Message.timestamp))
            )
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def save_image(self, message_db_id: int, image_data: dict) -> Image:
        async def _save_once() -> Image:
            async with self._session() as session:
                try:
                    image = Image(
                        message_id=message_db_id,
                        file_url=image_data.get("file_url"),
                        file_unique=image_data.get("file_unique"),
                        file_size=image_data.get("file_size"),
                        local_path=image_data.get("local_path"),
                        width=image_data.get("width"),
                        height=image_data.get("height"),
                        downloaded=image_data.get("downloaded", False),
                    )
                    session.add(image)

                    msg_stmt = select(Message).where(Message.id == message_db_id)
                    msg_result = await session.execute(msg_stmt)
                    msg = msg_result.scalar_one()
                    msg.has_image = True

                    await session.commit()
                    await session.refresh(image)
                    return image
                except Exception:
                    await session.rollback()
                    raise

        return await self._run_with_lock_retry("save_image", _save_once)

    async def update_image_local_path(
        self, image_id: int, local_path: str, downloaded: bool = True
    ):
        async def _update_once() -> None:
            async with self._session() as session:
                try:
                    stmt = select(Image).where(Image.id == image_id)
                    result = await session.execute(stmt)
                    image = result.scalar_one()
                    image.local_path = local_path
                    image.downloaded = downloaded
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        await self._run_with_lock_retry("update_image_local_path", _update_once)

    async def find_reusable_image_by_url(self, file_url: str) -> Image | None:
        async with self._session() as session:
            stmt = (
                select(Image)
                .where(
                    Image.file_url == file_url,
                    Image.downloaded,
                    Image.local_path.is_not(None),
                )
                .order_by(desc(Image.id))
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def apply_cached_image_to_message(
        self,
        message_db_id: int,
        file_url: str,
        local_path: str,
        file_unique: str | None,
        file_size: int | None,
        is_sticker: bool,
        sticker_confidence: float,
    ) -> None:
        async def _update_once() -> None:
            async with self._session() as session:
                try:
                    stmt = select(Image).where(
                        Image.message_id == message_db_id,
                        Image.file_url == file_url,
                    )
                    result = await session.execute(stmt)
                    image = result.scalar_one_or_none()
                    if image is None:
                        return
                    image.local_path = local_path
                    image.file_unique = file_unique
                    image.file_size = file_size
                    image.downloaded = True
                    image.is_sticker = is_sticker
                    image.sticker_confidence = sticker_confidence
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        await self._run_with_lock_retry("apply_cached_image_to_message", _update_once)

    async def get_monitored_chats(self) -> list[MonitoredChat]:
        async with self._session() as session:
            stmt = select(MonitoredChat).where(MonitoredChat.enabled)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def add_monitored_chat(
        self, chat_type: str, chat_id: str, chat_name: str | None = None
    ) -> MonitoredChat:
        async with self._session() as session:
            try:
                existing_stmt = select(MonitoredChat).where(
                    MonitoredChat.chat_type == chat_type,
                    MonitoredChat.chat_id == chat_id,
                )
                existing_result = await session.execute(existing_stmt)
                existing = existing_result.scalar_one_or_none()
                if existing:
                    existing.enabled = True
                    existing.chat_name = chat_name or existing.chat_name
                    await session.commit()
                    await session.refresh(existing)
                    return existing

                chat = MonitoredChat(
                    chat_type=chat_type,
                    chat_id=chat_id,
                    chat_name=chat_name,
                    enabled=True,
                )
                session.add(chat)
                await session.commit()
                await session.refresh(chat)
                return chat
            except Exception:
                await session.rollback()
                raise

    async def remove_monitored_chat(self, chat_type: str, chat_id: str) -> bool:
        async with self._session() as session:
            try:
                stmt = select(MonitoredChat).where(
                    MonitoredChat.chat_type == chat_type,
                    MonitoredChat.chat_id == chat_id,
                )
                result = await session.execute(stmt)
                chat = result.scalar_one_or_none()
                if not chat:
                    return False
                chat.enabled = False
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                raise

    async def is_chat_monitored(self, chat_type: str, chat_id: str) -> bool:
        async with self._session() as session:
            stmt = select(MonitoredChat).where(
                MonitoredChat.chat_type == chat_type,
                MonitoredChat.chat_id == chat_id,
                MonitoredChat.enabled,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    # ── Image/Video analysis persistence ──────────────────────────────

    async def save_image_analysis(
        self,
        *,
        file_unique: str,
        model_used: str,
        analysis_json: str,
        media_type: str = "image",
        image_type: str = "",
        confidence: float = 0.0,
        prompt_version: str = "",
        schema_version: str = "",
        image_id: int | None = None,
        message_id: int | None = None,
    ) -> None:
        async def _upsert() -> None:
            async with self._session() as session:
                try:
                    stmt = select(ImageAnalysis).where(
                        ImageAnalysis.file_unique == file_unique,
                        ImageAnalysis.model_used == model_used,
                    )
                    result = await session.execute(stmt)
                    row = result.scalar_one_or_none()
                    if row is None:
                        session.add(
                            ImageAnalysis(
                                file_unique=file_unique,
                                model_used=model_used,
                                analysis_json=analysis_json,
                                media_type=media_type,
                                image_type=image_type,
                                confidence=confidence,
                                prompt_version=prompt_version,
                                schema_version=schema_version,
                                image_id=image_id,
                                message_id=message_id,
                            )
                        )
                    else:
                        row.analysis_json = analysis_json
                        row.media_type = media_type
                        row.image_type = image_type
                        row.confidence = confidence
                        row.prompt_version = prompt_version
                        row.schema_version = schema_version
                        if image_id is not None:
                            row.image_id = image_id
                        if message_id is not None:
                            row.message_id = message_id
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        await self._run_with_lock_retry("save_image_analysis", _upsert)

    async def get_image_analysis(
        self,
        file_unique: str,
        model_used: str | None = None,
    ) -> ImageAnalysis | None:
        async with self._session() as session:
            stmt = select(ImageAnalysis).where(ImageAnalysis.file_unique == file_unique)
            if model_used:
                stmt = stmt.where(ImageAnalysis.model_used == model_used)
            stmt = stmt.order_by(desc(ImageAnalysis.updated_at)).limit(1)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_image_analyses_by_message(
        self, message_db_id: int
    ) -> list[ImageAnalysis]:
        async with self._session() as session:
            stmt = (
                select(ImageAnalysis)
                .where(ImageAnalysis.message_id == message_db_id)
                .order_by(desc(ImageAnalysis.updated_at))
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())


def _ensure_message_sender_columns(sync_conn) -> None:
    result = sync_conn.exec_driver_sql("PRAGMA table_info(messages)")
    rows = list(result.fetchall())
    if not rows:
        return
    columns = {row[1] for row in rows}
    if "sender_nickname" not in columns:
        sync_conn.exec_driver_sql(
            "ALTER TABLE messages ADD COLUMN sender_nickname VARCHAR"
        )
    if "sender_card" not in columns:
        sync_conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN sender_card VARCHAR")
