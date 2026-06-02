import asyncio
from datetime import datetime
from pathlib import Path

from plugins.qq_grok_reply.recorder_bridge import RecorderBridge
from plugins.qq_recorder.storage import MessageStorage


def _message_data(message_id: str, *, group_id: str = "30001", user_id: str = "20001"):
    return {
        "message_id": message_id,
        "user_id": user_id,
        "group_id": group_id,
        "chat_type": "group",
        "timestamp": datetime(2026, 6, 2, 12, 0),
        "raw_message": f"msg-{message_id}",
        "segments": [],
        "images": [],
        "replies": [],
        "forward_messages": [],
        "at_mentions": [],
        "app_shares": [],
    }


def test_recorder_bridge_waits_for_visible_row_and_gets_recent(tmp_path: Path):
    async def _run() -> None:
        db_path = tmp_path / "recorder.db"
        writer = MessageStorage(str(db_path))
        await writer.init_db()

        bridge = RecorderBridge()
        await bridge.connect_existing(str(db_path))

        async def _save_later():
            await asyncio.sleep(0.05)
            await writer.save_message(_message_data("m-late"))
            await writer.save_message(_message_data("m-recent-1"))
            await writer.save_message(_message_data("m-recent-2"))

        task = asyncio.create_task(_save_later())
        message = await bridge.wait_until_visible(
            "m-late", timeout_ms=200, backoff_ms=[20, 40, 60]
        )
        await task

        assert message is not None
        assert message.message_id == "m-late"

        recent = await bridge.get_recent("group", "30001", 2)
        assert [item.message_id for item in recent] == ["m-recent-2", "m-recent-1"]

        await bridge.close()
        await writer.close()

    asyncio.run(_run())
