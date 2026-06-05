import asyncio
from datetime import datetime, timedelta

from sqlalchemy import and_, asc, desc, or_, select
from sqlalchemy.orm import selectinload

from ..compat import import_sibling_plugin_module

_models = import_sibling_plugin_module("qq_recorder.models")
_storage = import_sibling_plugin_module("qq_recorder.storage")
Message = _models.Message
ForwardMessage = _models.ForwardMessage
init_engine = _models.init_engine
MessageStorage = _storage.MessageStorage
_ensure_message_sender_columns = _storage._ensure_message_sender_columns


class RecorderBridge:
    def __init__(self):
        self.storage: MessageStorage | None = None

    async def connect_existing(self, recorder_db: str) -> None:
        storage = MessageStorage(recorder_db)
        storage.engine, storage.AsyncSessionLocal = await init_engine(recorder_db)
        async with storage.engine.begin() as conn:
            await conn.run_sync(_ensure_message_sender_columns)
        self.storage = storage

    async def close(self) -> None:
        if self.storage is not None:
            await self.storage.close()

    async def wait_until_visible(
        self,
        source_message_id: str,
        timeout_ms: int,
        backoff_ms: list[int],
    ) -> Message | None:
        message = await self.get_message(source_message_id)
        if message is not None:
            return message

        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
        backoffs = backoff_ms or [50]
        attempt = 0
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            delay = backoffs[min(attempt, len(backoffs) - 1)]
            await asyncio.sleep(min(delay / 1000, remaining))
            message = await self.get_message(source_message_id)
            if message is not None:
                return message
            attempt += 1
        return await self.get_message(source_message_id)

    async def get_message(self, source_message_id: str) -> Message | None:
        assert self.storage is not None, "connect_existing() not called"
        return await self.storage.get_message(source_message_id)

    async def get_recent(
        self, chat_type: str, chat_id: str, limit: int
    ) -> list[Message]:
        return await self.get_candidates(chat_type, chat_id, limit=limit)

    async def get_recent_window(
        self,
        chat_type: str,
        chat_id: str,
        *,
        limit: int,
        since_minutes: int,
        before_or_at: datetime | None,
    ) -> list[Message]:
        return await self.get_candidates(
            chat_type,
            chat_id,
            limit=limit,
            since_minutes=since_minutes,
            before_or_at=before_or_at,
        )

    async def get_candidates(
        self,
        chat_type: str,
        chat_id: str,
        *,
        limit: int,
        since_minutes: int | None = None,
        before_or_at: datetime | None = None,
    ) -> list[Message]:
        assert self.storage is not None, "connect_existing() not called"
        async with self.storage._session() as session:
            stmt = (
                self._message_stmt()
                .order_by(desc(Message.timestamp), desc(Message.id))
                .limit(limit)
            )
            stmt = stmt.where(*self._chat_filters(chat_type, chat_id))
            if before_or_at is not None:
                stmt = stmt.where(Message.timestamp <= before_or_at)
            if since_minutes is not None and before_or_at is not None:
                stmt = stmt.where(
                    Message.timestamp >= before_or_at - timedelta(minutes=since_minutes)
                )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_reply_chain(
        self, source_msg: Message, *, max_depth: int
    ) -> list[Message]:
        chain: list[Message] = []
        current = source_msg
        visited = {str(getattr(source_msg, "message_id", "") or "")}
        for _ in range(max_depth):
            reply_to_id = _first_reply_id(current)
            if not reply_to_id or reply_to_id in visited:
                break
            reply_msg = await self.get_message(reply_to_id)
            if reply_msg is None:
                break
            chain.append(reply_msg)
            visited.add(reply_to_id)
            current = reply_msg
        return chain

    async def get_neighbors(
        self,
        chat_type: str,
        chat_id: str,
        *,
        anchor: Message,
        before_limit: int,
        after_limit: int,
    ) -> list[Message]:
        assert self.storage is not None, "connect_existing() not called"
        if before_limit <= 0 and after_limit <= 0:
            return []

        anchor_time = getattr(anchor, "timestamp", None)
        anchor_db_id = getattr(anchor, "id", None)
        if anchor_time is None or anchor_db_id is None:
            return []

        async with self.storage._session() as session:
            before_stmt = (
                self._message_stmt()
                .where(*self._chat_filters(chat_type, chat_id))
                .where(
                    or_(
                        Message.timestamp < anchor_time,
                        and_(
                            Message.timestamp == anchor_time,
                            Message.id < anchor_db_id,
                        ),
                    )
                )
                .order_by(desc(Message.timestamp), desc(Message.id))
                .limit(before_limit)
            )
            after_stmt = (
                self._message_stmt()
                .where(*self._chat_filters(chat_type, chat_id))
                .where(
                    or_(
                        Message.timestamp > anchor_time,
                        and_(
                            Message.timestamp == anchor_time,
                            Message.id > anchor_db_id,
                        ),
                    )
                )
                .order_by(asc(Message.timestamp), asc(Message.id))
                .limit(after_limit)
            )
            before_result = await session.execute(before_stmt)
            after_result = await session.execute(after_stmt)
            before_messages = list(reversed(before_result.scalars().all()))
            after_messages = list(after_result.scalars().all())
            return before_messages + after_messages

    @staticmethod
    def _message_stmt():
        return select(Message).options(
            selectinload(Message.segments),
            selectinload(Message.images),
            selectinload(Message.videos),
            selectinload(Message.replies),
            selectinload(Message.forward_messages).options(
                selectinload(ForwardMessage.children)
            ),
            selectinload(Message.at_mentions),
            selectinload(Message.app_shares),
        )

    @staticmethod
    def _chat_filters(chat_type: str, chat_id: str):
        if chat_type == "group":
            return (Message.chat_type == "group", Message.group_id == chat_id)
        return (Message.chat_type == "private", Message.user_id == chat_id)


def _first_reply_id(message) -> str | None:
    replies = getattr(message, "replies", []) or []
    if not replies:
        return None
    value = getattr(replies[0], "reply_to_message_id", None)
    return str(value) if value else None


async def save_analysis(
    bridge: RecorderBridge | None,
    *,
    file_unique: str,
    model_used: str,
    analysis_json: str,
    media_type: str = "image",
    image_type: str = "",
    semantic_text: str = "",
    confidence: float = 0.0,
    prompt_version: str = "",
    schema_version: str = "",
    image_id: int | None = None,
    video_id: int | None = None,
    message_db_id: int | None = None,
) -> None:
    if bridge is None or bridge.storage is None:
        return
    await bridge.storage.save_image_analysis(
        file_unique=file_unique,
        model_used=model_used,
        analysis_json=analysis_json,
        media_type=media_type,
        image_type=image_type,
        semantic_text=semantic_text,
        confidence=confidence,
        prompt_version=prompt_version,
        schema_version=schema_version,
        image_id=image_id,
        video_id=video_id,
        message_id=message_db_id,
    )
