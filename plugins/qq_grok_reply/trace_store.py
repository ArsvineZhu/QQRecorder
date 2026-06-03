import json

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import desc

from .models import Base, ReplyTrace, init_engine

_TOPIC_COLUMNS = {
    "topic_title": "VARCHAR DEFAULT ''",
    "topic_summary": "TEXT DEFAULT ''",
    "topic_participants_json": "TEXT DEFAULT '[]'",
    "topic_selected_ids_json": "TEXT DEFAULT '[]'",
    "topic_candidate_count": "INTEGER DEFAULT 0",
    "topic_confidence": "FLOAT DEFAULT 0.0",
    "topic_error_code": "VARCHAR DEFAULT ''",
    "topic_fallback_used": "BOOLEAN DEFAULT 0",
}


class TraceStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = None
        self.AsyncSessionLocal = None

    async def init_db(self) -> None:
        self.engine, self.AsyncSessionLocal = await init_engine(self.db_path)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_ensure_topic_columns)

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
        topic_title: str = "",
        topic_summary: str = "",
        topic_participants_json: str = "[]",
        topic_selected_ids_json: str = "[]",
        topic_candidate_count: int = 0,
        topic_confidence: float = 0.0,
        topic_error_code: str = "",
        topic_fallback_used: bool = False,
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
                topic_title=topic_title,
                topic_summary=topic_summary,
                topic_participants_json=topic_participants_json,
                topic_selected_ids_json=topic_selected_ids_json,
                topic_candidate_count=topic_candidate_count,
                topic_confidence=topic_confidence,
                topic_error_code=topic_error_code,
                topic_fallback_used=topic_fallback_used,
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
        topic_error_code: str | None = None,
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
            if topic_error_code is not None:
                trace.topic_error_code = topic_error_code
            await session.commit()

    async def update_trace_context(
        self,
        trace_id: int,
        *,
        context_ids: list[str],
        prompt_variant: str,
        topic_title: str = "",
        topic_summary: str = "",
        topic_participants_json: str = "[]",
        topic_selected_ids_json: str = "[]",
        topic_candidate_count: int = 0,
        topic_confidence: float = 0.0,
        topic_error_code: str = "",
        topic_fallback_used: bool = False,
    ) -> None:
        async with self._session() as session:
            trace = await session.get(ReplyTrace, trace_id)
            assert trace is not None, f"ReplyTrace {trace_id} does not exist"
            trace.context_ids = json.dumps(context_ids, ensure_ascii=False)
            trace.prompt_variant = prompt_variant
            trace.topic_title = topic_title
            trace.topic_summary = topic_summary
            trace.topic_participants_json = topic_participants_json
            trace.topic_selected_ids_json = topic_selected_ids_json
            trace.topic_candidate_count = topic_candidate_count
            trace.topic_confidence = topic_confidence
            trace.topic_error_code = topic_error_code
            trace.topic_fallback_used = topic_fallback_used
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


def _ensure_topic_columns(sync_conn) -> None:
    columns = {
        column["name"] for column in inspect(sync_conn).get_columns("reply_traces")
    }
    for name, ddl in _TOPIC_COLUMNS.items():
        if name not in columns:
            sync_conn.execute(text(f"ALTER TABLE reply_traces ADD COLUMN {name} {ddl}"))
