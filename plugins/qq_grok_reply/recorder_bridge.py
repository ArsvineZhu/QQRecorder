import asyncio

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from .compat import import_sibling_plugin_module

_models = import_sibling_plugin_module("qq_recorder.models")
_storage = import_sibling_plugin_module("qq_recorder.storage")
Message = _models.Message
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
        for delay in backoff_ms:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(delay / 1000, remaining))
            message = await self.get_message(source_message_id)
            if message is not None:
                return message
        return await self.get_message(source_message_id)

    async def get_message(self, source_message_id: str) -> Message | None:
        assert self.storage is not None, "connect_existing() not called"
        return await self.storage.get_message(source_message_id)

    async def get_recent(
        self, chat_type: str, chat_id: str, limit: int
    ) -> list[Message]:
        assert self.storage is not None, "connect_existing() not called"
        async with self.storage._session() as session:
            stmt = (
                select(Message)
                .options(
                    selectinload(Message.images),
                    selectinload(Message.at_mentions),
                    selectinload(Message.app_shares),
                )
                .order_by(desc(Message.timestamp), desc(Message.id))
                .limit(limit)
            )
            if chat_type == "group":
                stmt = stmt.where(
                    Message.chat_type == "group", Message.group_id == chat_id
                )
            else:
                stmt = stmt.where(
                    Message.chat_type == "private", Message.user_id == chat_id
                )
            result = await session.execute(stmt)
            return list(result.scalars().all())
