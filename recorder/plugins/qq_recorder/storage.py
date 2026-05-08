from typing import Optional
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Base, init_engine, Message, MessageSegment, Image, Reply, ForwardMessage, AtMention, MonitoredChat

class MessageStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = None
        self.AsyncSessionLocal = None
        
    async def init_db(self):
        self.engine, self.AsyncSessionLocal = await init_engine(self.db_path)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def close(self):
        if self.engine:
            await self.engine.dispose()
    
    async def save_message(self, message_data: dict) -> int:
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            try:
                message = Message(
                    message_id=message_data["message_id"],
                    user_id=message_data["user_id"],
                    group_id=message_data["group_id"],
                    chat_type=message_data["chat_type"],
                    timestamp=message_data["timestamp"],
                    raw_message=message_data["raw_message"],
                    has_image=len(message_data.get("images", [])) > 0,
                    has_reply=len(message_data.get("replies", [])) > 0,
                    has_forward=len(message_data.get("forward_messages", [])) > 0,
                    has_at=len(message_data.get("at_mentions", [])) > 0
                )
                session.add(message)
                await session.flush()
                
                for seg in message_data.get("segments", []):
                    segment = MessageSegment(
                        message_id=message.id,
                        segment_type=seg["segment_type"],
                        segment_order=seg["segment_order"],
                        segment_data=seg["segment_data"]
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
                        downloaded=img.get("downloaded", False)
                    )
                    session.add(image)
                
                for reply in message_data.get("replies", []):
                    reply_obj = Reply(
                        message_id=message.id,
                        reply_to_message_id=reply["reply_to_message_id"]
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
                        forward_id=forward_data.get("forward_id")
                    )
                    session.add(forward)
                    await session.flush()
                    for child in forward_data.get("children", []):
                        await save_forward(child, forward.id)
                
                for forward in message_data.get("forward_messages", []):
                    await save_forward(forward)
                
                for at in message_data.get("at_mentions", []):
                    at_obj = AtMention(
                        message_id=message.id,
                        target_user_id=at["target_user_id"]
                    )
                    session.add(at_obj)
                
                await session.commit()
                return message.id
            except Exception:
                await session.rollback()
                raise
    
    async def get_message(self, message_id: str) -> Optional[Message]:
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(Message).where(Message.message_id == message_id)\
                .options(
                    selectinload(Message.segments),
                    selectinload(Message.images),
                    selectinload(Message.replies),
                    selectinload(Message.forward_messages).options(selectinload(ForwardMessage.children)),
                    selectinload(Message.at_mentions)
                )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
    
    async def get_recent_messages(self, chat_type: str = None, chat_id: str = None, limit: int = 10) -> list[Message]: # pyright: ignore[reportArgumentType]
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(Message).options(
                selectinload(Message.images),
                selectinload(Message.at_mentions),
            ).order_by(desc(Message.timestamp))
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
    
    async def count_messages(self, chat_type: str = None, chat_id: str = None) -> int: # pyright: ignore[reportArgumentType]
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
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
    
    async def count_images(self, chat_type: str = None, chat_id: str = None) -> int: # pyright: ignore[reportArgumentType]
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(func.count(Image.id)).join(Message, Image.message_id == Message.id)
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one()
    
    async def count_downloaded_images(self, chat_type: str = None, chat_id: str = None) -> int: # pyright: ignore[reportArgumentType]
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(func.count(Image.id)).join(Message, Image.message_id == Message.id).where(Image.downloaded == True)
            if chat_type:
                stmt = stmt.where(Message.chat_type == chat_type)
            if chat_id:
                if chat_type == "group":
                    stmt = stmt.where(Message.group_id == chat_id)
                else:
                    stmt = stmt.where(Message.user_id == chat_id)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def search_messages(self, keyword: str, chat_type: str = None, chat_id: str = None, limit: int = 10) -> list[Message]: # pyright: ignore[reportArgumentType]
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(Message).options(
                selectinload(Message.images),
                selectinload(Message.at_mentions),
            ).where(Message.raw_message.contains(keyword)).order_by(desc(Message.timestamp))
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
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            try:
                image = Image(
                    message_id=message_db_id,
                    file_url=image_data.get("file_url"),
                    file_unique=image_data.get("file_unique"),
                    file_size=image_data.get("file_size"),
                    local_path=image_data.get("local_path"),
                    width=image_data.get("width"),
                    height=image_data.get("height"),
                    downloaded=image_data.get("downloaded", False)
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
    
    async def update_image_local_path(self, image_id: int, local_path: str, downloaded: bool = True):
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
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
    
    async def get_monitored_chats(self) -> list[MonitoredChat]:
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(MonitoredChat).where(MonitoredChat.enabled == True)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    
    async def add_monitored_chat(self, chat_type: str, chat_id: str, chat_name: str = None) -> MonitoredChat: # pyright: ignore[reportArgumentType]
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            try:
                existing_stmt = select(MonitoredChat).where(
                    MonitoredChat.chat_type == chat_type,
                    MonitoredChat.chat_id == chat_id
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
                    enabled=True
                )
                session.add(chat)
                await session.commit()
                await session.refresh(chat)
                return chat
            except Exception:
                await session.rollback()
                raise
    
    async def remove_monitored_chat(self, chat_type: str, chat_id: str) -> bool:
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            try:
                stmt = select(MonitoredChat).where(
                    MonitoredChat.chat_type == chat_type,
                    MonitoredChat.chat_id == chat_id
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
        async with self.AsyncSessionLocal() as session: # pyright: ignore[reportOptionalCall]
            stmt = select(MonitoredChat).where(
                MonitoredChat.chat_type == chat_type,
                MonitoredChat.chat_id == chat_id,
                MonitoredChat.enabled == True
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
