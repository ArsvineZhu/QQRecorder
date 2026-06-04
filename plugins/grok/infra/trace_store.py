import json

from sqlalchemy import inspect, select, text
from sqlalchemy.sql import desc

from ..models import AgentReplyTrace, Base, init_engine

_TRACE_COLUMNS = {
    "parser_version": "VARCHAR DEFAULT 'v1'",
    "context_version": "VARCHAR DEFAULT 'v1'",
    "profile_version": "VARCHAR DEFAULT 'v1'",
    "working_context_json": "TEXT DEFAULT '{}'",
}


class AgentTraceStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = None
        self.AsyncSessionLocal = None

    async def init_db(self) -> None:
        self.engine, self.AsyncSessionLocal = await init_engine(self.db_path)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_ensure_trace_columns)

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
        chat_type: str,
        chat_id: str,
        user_id: str,
        decision_seed: str,
        trigger_reason: str,
        parser_version: str = "v1",
        context_version: str = "v1",
        profile_version: str = "v1",
        working_context_json: str = "{}",
    ) -> int:
        async with self._session() as session:
            trace = AgentReplyTrace(
                source_message_id=source_message_id,
                chat_type=chat_type,
                chat_id=chat_id,
                user_id=user_id,
                decision_seed=decision_seed,
                trigger_reason=trigger_reason,
                parser_version=parser_version,
                context_version=context_version,
                profile_version=profile_version,
                working_context_json=working_context_json,
            )
            session.add(trace)
            await session.commit()
            await session.refresh(trace)
            return trace.id

    async def add_step(self, trace_id: int, step) -> None:
        async with self._session() as session:
            trace = await session.get(AgentReplyTrace, trace_id)
            assert trace is not None
            items = json.loads(trace.tool_steps_json or "[]")
            items.append(
                {
                    "kind": step.kind,
                    "tool_name": step.tool_name,
                    "status": step.status,
                    "summary": step.summary,
                }
            )
            trace.tool_steps_json = json.dumps(items, ensure_ascii=False)
            await session.commit()

    async def finish_working_context(
        self,
        trace_id: int,
        working_context_json: str,
    ) -> None:
        async with self._session() as session:
            trace = await session.get(AgentReplyTrace, trace_id)
            assert trace is not None
            trace.working_context_json = working_context_json
            await session.commit()

    async def finish_trace(
        self,
        trace_id: int,
        *,
        model_name: str,
        response_text: str,
        error_code: str | None,
        sent: bool,
        sent_message_id: str | None,
        sent_parts: int,
        latency_ms: int,
    ) -> None:
        async with self._session() as session:
            trace = await session.get(AgentReplyTrace, trace_id)
            assert trace is not None
            trace.model_name = model_name
            trace.response_text = response_text
            trace.error_code = error_code
            trace.sent = sent
            trace.sent_message_id = sent_message_id
            trace.sent_parts = sent_parts
            trace.latency_ms = latency_ms
            await session.commit()

    async def get_sent_message_ids(
        self,
        chat_type: str,
        chat_id: str,
        *,
        limit: int = 50,
    ) -> set[str]:
        async with self._session() as session:
            stmt = (
                select(AgentReplyTrace.sent_message_id)
                .where(
                    AgentReplyTrace.chat_type == chat_type,
                    AgentReplyTrace.chat_id == chat_id,
                    AgentReplyTrace.sent.is_(True),
                    AgentReplyTrace.sent_message_id.is_not(None),
                )
                .order_by(desc(AgentReplyTrace.created_at), desc(AgentReplyTrace.id))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return {str(item) for item in result.scalars() if item}


def _ensure_trace_columns(sync_conn) -> None:
    columns = {
        column["name"]
        for column in inspect(sync_conn).get_columns("agent_reply_traces")
    }
    for name, ddl in _TRACE_COLUMNS.items():
        if name not in columns:
            sync_conn.execute(
                text(f"ALTER TABLE agent_reply_traces ADD COLUMN {name} {ddl}")
            )
