from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class AgentReplyTrace(Base):
    __tablename__ = "agent_reply_traces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_message_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    chat_type: Mapped[str] = mapped_column(String, nullable=False)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    decision_seed: Mapped[str] = mapped_column(String, nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String, nullable=False)
    tool_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    parser_version: Mapped[str] = mapped_column(String, default="v1")
    context_version: Mapped[str] = mapped_column(String, default="v1")
    profile_version: Mapped[str] = mapped_column(String, default="v1")
    working_context_json: Mapped[str] = mapped_column(Text, default="{}")
    model_name: Mapped[str] = mapped_column(String, default="")
    response_text: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_parts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class AgentConversationSession(Base):
    __tablename__ = "agent_conversation_sessions"

    chat_type: Mapped[str] = mapped_column(String, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String, primary_key=True)
    messages_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
    )


class AgentProfileSnapshot(Base):
    __tablename__ = "agent_profile_snapshots"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, default="")
    preferred_name: Mapped[str] = mapped_column(String, default="")
    group_instruction: Mapped[str] = mapped_column(Text, default="")
    private_instruction: Mapped[str] = mapped_column(Text, default="")
    language_style: Mapped[str] = mapped_column(String, default="")
    habit_preferences_json: Mapped[str] = mapped_column(Text, default="[]")
    profile_version: Mapped[str] = mapped_column(String, default="v1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
    )


async def init_engine(db_path: str):
    db_url = (
        db_path
        if "://" in db_path
        else f"sqlite+aiosqlite:///{Path(db_path).resolve().as_posix()}"
    )
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
