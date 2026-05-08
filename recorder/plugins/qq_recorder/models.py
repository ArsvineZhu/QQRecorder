from datetime import datetime
from sqlalchemy import func, ForeignKey, String, Text, Integer, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

class Base(DeclarativeBase):
    pass

class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    group_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chat_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    has_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    has_forward: Mapped[bool] = mapped_column(Boolean, default=False)
    has_at: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    
    segments: Mapped[list["MessageSegment"]] = relationship("MessageSegment", back_populates="message", cascade="all, delete-orphan")
    images: Mapped[list["Image"]] = relationship("Image", back_populates="message", cascade="all, delete-orphan", order_by="Image.id")
    replies: Mapped[list["Reply"]] = relationship("Reply", back_populates="message", cascade="all, delete-orphan")
    forward_messages: Mapped[list["ForwardMessage"]] = relationship("ForwardMessage", back_populates="message", cascade="all, delete-orphan")
    at_mentions: Mapped[list["AtMention"]] = relationship("AtMention", back_populates="message", cascade="all, delete-orphan")

class MessageSegment(Base):
    __tablename__ = "message_segments"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    segment_type: Mapped[str] = mapped_column(String, nullable=False)
    segment_order: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_data: Mapped[str] = mapped_column(Text, nullable=False)
    
    message: Mapped["Message"] = relationship("Message", back_populates="segments")

class Image(Base):
    __tablename__ = "images"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    file_url: Mapped[str | None] = mapped_column(String, nullable=True)
    file_unique: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    
    message: Mapped["Message"] = relationship("Message", back_populates="images")

class Reply(Base):
    __tablename__ = "replies"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    reply_to_message_id: Mapped[str] = mapped_column(String, nullable=False)
    
    message: Mapped["Message"] = relationship("Message", back_populates="replies")

class ForwardMessage(Base):
    __tablename__ = "forward_messages"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    parent_forward_id: Mapped[int | None] = mapped_column(ForeignKey("forward_messages.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    nickname: Mapped[str | None] = mapped_column(String, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    content_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_id: Mapped[str | None] = mapped_column(String, nullable=True)
    
    message: Mapped["Message"] = relationship("Message", back_populates="forward_messages")
    children: Mapped[list["ForwardMessage"]] = relationship("ForwardMessage", back_populates="parent", cascade="all, delete-orphan")
    parent: Mapped["ForwardMessage | None"] = relationship("ForwardMessage", back_populates="children", remote_side=[id])

class AtMention(Base):
    __tablename__ = "at_mentions"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    target_user_id: Mapped[str] = mapped_column(String, nullable=False)
    
    message: Mapped["Message"] = relationship("Message", back_populates="at_mentions")

class MonitoredChat(Base):
    __tablename__ = "monitored_chats"
    __table_args__ = (
        UniqueConstraint("chat_type", "chat_id", name="_chat_type_chat_id_uc"),
    )
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_type: Mapped[str] = mapped_column(String, nullable=False)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    chat_name: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

async def init_engine(db_path: str):
    engine = create_async_engine(db_path, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    return engine, AsyncSessionLocal
