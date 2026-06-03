import asyncio
from datetime import datetime
from pathlib import Path

from plugins.qq_grok_reply.infra import RecorderBridge
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
        assert message.segments == []

        recent = await bridge.get_recent("group", "30001", 2)
        assert [item.message_id for item in recent] == ["m-recent-2", "m-recent-1"]

        await bridge.close()
        await writer.close()

    asyncio.run(_run())


def test_recorder_bridge_reads_reply_chain_neighbors_and_window(tmp_path: Path):
    async def _run() -> None:
        db_path = tmp_path / "recorder.db"
        writer = MessageStorage(str(db_path))
        await writer.init_db()

        timestamps = {
            "m-before": datetime(2026, 6, 2, 11, 58),
            "m-root": datetime(2026, 6, 2, 12, 0),
            "m-mid": datetime(2026, 6, 2, 12, 2),
            "m-side": datetime(2026, 6, 2, 12, 3),
            "m-current": datetime(2026, 6, 2, 12, 4),
            "m-after": datetime(2026, 6, 2, 12, 5),
        }

        for message_id in (
            "m-before",
            "m-root",
            "m-mid",
            "m-side",
            "m-current",
            "m-after",
        ):
            payload = _message_data(message_id)
            payload["timestamp"] = timestamps[message_id]
            payload["segments"] = [
                {
                    "segment_type": "text",
                    "segment_order": 0,
                    "segment_data": f'{{"text": "msg-{message_id}"}}',
                }
            ]
            if message_id == "m-mid":
                payload["replies"] = [{"reply_to_message_id": "m-root"}]
            if message_id == "m-current":
                payload["replies"] = [{"reply_to_message_id": "m-mid"}]
            await writer.save_message(payload)

        bridge = RecorderBridge()
        await bridge.connect_existing(str(db_path))

        source = await bridge.get_message("m-current")
        assert source is not None
        assert len(source.segments) == 1

        recent = await bridge.get_recent_window(
            "group",
            "30001",
            limit=3,
            since_minutes=30,
            before_or_at=timestamps["m-current"],
        )
        chain = await bridge.get_reply_chain(source, max_depth=5)
        neighbors = await bridge.get_neighbors(
            "group",
            "30001",
            anchor=chain[0],
            before_limit=1,
            after_limit=1,
        )

        assert [item.message_id for item in recent] == ["m-current", "m-side", "m-mid"]
        assert [item.message_id for item in chain] == ["m-mid", "m-root"]
        assert [item.message_id for item in neighbors] == ["m-root", "m-side"]
        assert all(len(item.segments) == 1 for item in recent)
        assert all(len(item.segments) == 1 for item in chain)
        assert all(len(item.segments) == 1 for item in neighbors)

        await bridge.close()
        await writer.close()

    asyncio.run(_run())
