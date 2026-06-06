import json

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from ..models import AgentConversationSession, Base, init_engine


class AgentConversationSessionStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = None
        self.AsyncSessionLocal = None

    async def init_db(self) -> None:
        self.engine, self.AsyncSessionLocal = await init_engine(self.db_path)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    def _session(self):
        assert self.AsyncSessionLocal is not None, "init_db() not called"
        return self.AsyncSessionLocal()

    async def get_session(self, chat_type: str, chat_id: str) -> list[dict]:
        async with self._session() as session:
            stmt = select(AgentConversationSession).where(
                AgentConversationSession.chat_type == str(chat_type or ""),
                AgentConversationSession.chat_id == str(chat_id or ""),
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record is None:
                return []
            payload = json.loads(record.messages_json or "[]")
            return payload if isinstance(payload, list) else []

    async def upsert_session(
        self,
        chat_type: str,
        chat_id: str,
        messages: list[dict],
    ) -> None:
        async with self._session() as session:
            payload = json.dumps(messages, ensure_ascii=False)
            stmt = insert(AgentConversationSession).values(
                chat_type=str(chat_type or ""),
                chat_id=str(chat_id or ""),
                messages_json=payload,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    AgentConversationSession.chat_type,
                    AgentConversationSession.chat_id,
                ],
                set_={"messages_json": payload},
            )
            await session.execute(stmt)
            await session.commit()
