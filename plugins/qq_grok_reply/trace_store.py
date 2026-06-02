import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import desc

from .models import Base, ReplyTrace, init_engine


class TraceStore:
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

    async def insert_trace(
        self,
        *,
        source_message_id: str,
        source_message_db_id: int | None,
        chat_type: str,
        chat_id: str,
        user_id: str,
        decision_seed: str,
        decision: str,
        trigger_reason: str,
        context_ids: list[str],
        prompt_variant: str,
    ) -> int:
        existing = await self.get_by_source_message_id(source_message_id)
        if existing is not None:
            return existing.id

        async with self._session() as session:
            trace = ReplyTrace(
                source_message_id=source_message_id,
                source_message_db_id=source_message_db_id,
                chat_type=chat_type,
                chat_id=chat_id,
                user_id=user_id,
                decision_seed=decision_seed,
                decision=decision,
                trigger_reason=trigger_reason,
                context_ids=json.dumps(context_ids, ensure_ascii=False),
                prompt_variant=prompt_variant,
            )
            session.add(trace)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self.get_by_source_message_id(source_message_id)
                if existing is None:
                    raise
                return existing.id
            await session.refresh(trace)
            return trace.id

    async def finish_trace(
        self,
        trace_id: int,
        *,
        decision: str,
        model_name: str,
        model_request_summary: str,
        model_response_summary: str,
        latency_ms: int,
        error_code: str | None,
        sent: bool,
        sent_message_id: str | None,
        sent_parts: int,
    ) -> None:
        async with self._session() as session:
            trace = await session.get(ReplyTrace, trace_id)
            assert trace is not None, f"ReplyTrace {trace_id} does not exist"
            trace.decision = decision
            trace.model_name = model_name
            trace.model_request_summary = model_request_summary
            trace.model_response_summary = model_response_summary
            trace.latency_ms = latency_ms
            trace.error_code = error_code
            trace.sent = sent
            trace.sent_message_id = sent_message_id
            trace.sent_parts = sent_parts
            await session.commit()

    async def get_by_source_message_id(
        self, source_message_id: str
    ) -> ReplyTrace | None:
        async with self._session() as session:
            stmt = select(ReplyTrace).where(
                ReplyTrace.source_message_id == source_message_id
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_sent_message_ids(
        self, chat_type: str, chat_id: str, *, limit: int = 50
    ) -> set[str]:
        async with self._session() as session:
            stmt = (
                select(ReplyTrace.sent_message_id)
                .where(
                    ReplyTrace.chat_type == chat_type,
                    ReplyTrace.chat_id == chat_id,
                    ReplyTrace.sent.is_(True),
                    ReplyTrace.sent_message_id.is_not(None),
                )
                .order_by(desc(ReplyTrace.created_at), desc(ReplyTrace.id))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return {str(item) for item in result.scalars() if item}
