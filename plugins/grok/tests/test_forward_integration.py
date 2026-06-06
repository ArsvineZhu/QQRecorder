import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from plugins.grok.infra.recorder_bridge import RecorderBridge
from plugins.grok.tools.context_tools import build_context_tools
from plugins.qq_recorder.config import build_config
from plugins.qq_recorder.processors import MessageProcessor
from plugins.qq_recorder.storage import MessageStorage


class _ForwardAPI:
    class qq:
        class query:
            @staticmethod
            async def get_forward_msg(_forward_id: str) -> dict:
                return {
                    "messages": [
                        {
                            "sender": {"user_id": "20001", "nickname": "阿梓"},
                            "content": [
                                {"type": "text", "data": {"text": "转发第一句"}},
                                {
                                    "type": "image",
                                    "data": {"url": "https://example/a.png"},
                                },
                            ],
                        }
                    ]
                }


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None

    def error(self, *_args, **_kwargs) -> None:
        return None


def test_recorder_forward_storage_is_visible_to_grok_tools(tmp_path: Path):
    async def _run():
        db_path = tmp_path / "recorder.db"
        settings = build_config(
            {
                "monitor_all": True,
                "image": {"download": False},
                "forward": {"parse_content": True},
                "backup": {"enabled": False},
                "storage": {"database": str(db_path)},
            }
        )
        storage = MessageStorage(str(db_path))
        await storage.init_db()
        processor = MessageProcessor(storage, settings, _ForwardAPI(), _DummyLogger())
        await processor.process_message(
            {
                "message_type": "group",
                "message_id": "m-forward-bridge",
                "user_id": "u1",
                "group_id": "g1",
                "time": int(datetime.now().timestamp()),
                "raw_message": "[CQ:forward,id=fwd-1]",
                "message": [{"type": "forward", "data": {"id": "fwd-1"}}],
                "sender": {"nickname": "tester", "card": ""},
            }
        )
        await storage.close()

        bridge = RecorderBridge()
        await bridge.connect_existing(str(db_path))
        try:
            source_msg = await bridge.get_message("m-forward-bridge")
            assert source_msg is not None

            plugin = SimpleNamespace(_bridge=bridge, api=_ForwardAPI())
            tools = {item.name: item for item in build_context_tools(plugin)}

            forward_result = await tools["extract_forward"].handler(
                {"source_msg": source_msg},
                {"message_id": "m-forward-bridge"},
            )
            context_result = await tools["load_context"].handler(
                {"source_msg": source_msg, "chat_type": "group", "chat_id": "g1"},
                {
                    "limit": 5,
                    "since_minutes": 30,
                    "include_forward_preview": True,
                },
            )

            assert forward_result.status == "ok"
            assert (
                forward_result.data["forward_messages"][0]["content_summary"]
                == "转发第一句[图片]"
            )
            assert context_result.status == "ok"
            payload = context_result.data["messages"][0]
            assert payload["message_id"] == "m-forward-bridge"
            assert payload["has_forward"] is True
            assert (
                payload["forward_preview"][0]["content_summary"] == "转发第一句[图片]"
            )
        finally:
            await bridge.close()

    asyncio.run(_run())
