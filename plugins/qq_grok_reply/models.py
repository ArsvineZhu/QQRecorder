from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class ReplyTrace(Base):
    __tablename__ = "reply_traces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_message_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source_message_db_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_type: Mapped[str] = mapped_column(String, nullable=False)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    decision_seed: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String, nullable=False)
    context_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    prompt_variant: Mapped[str] = mapped_column(String, nullable=False)
    topic_title: Mapped[str] = mapped_column(String, default="")
    topic_summary: Mapped[str] = mapped_column(Text, default="")
    topic_participants_json: Mapped[str] = mapped_column(Text, default="[]")
    topic_selected_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    topic_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    topic_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    topic_error_code: Mapped[str] = mapped_column(String, default="")
    topic_fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    model_name: Mapped[str] = mapped_column(String, default="")
    model_request_summary: Mapped[str] = mapped_column(Text, default="")
    model_response_summary: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_parts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


async def init_engine(db_path: str):
    db_url = (
        db_path
        if "://" in db_path
        else f"sqlite+aiosqlite:///{Path(db_path).resolve().as_posix()}"
    )
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
