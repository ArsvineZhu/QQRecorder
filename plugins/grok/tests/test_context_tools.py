import asyncio
from datetime import datetime
from types import SimpleNamespace

from plugins.grok.tools.context_tools import build_context_tools


class _BridgeStub:
    def __init__(self, source, chain=None, recent=None):
        self.source = source
        self.chain = chain or []
        self.recent = recent or []

    async def get_message(self, message_id: str):
        if message_id == str(self.source.message_id):
            return self.source
        return None

    async def get_reply_chain(self, _source_msg, *, max_depth: int):
        return self.chain[:max_depth]

    async def get_recent_window(
        self,
        _chat_type: str,
        _chat_id: str,
        *,
        limit: int,
        since_minutes: int,
        before_or_at,
    ):
        assert since_minutes == 30
        assert before_or_at == self.source.timestamp
        return self.recent[:limit]


def _message(message_id: str, raw_message: str):
    return SimpleNamespace(
        message_id=message_id,
        user_id="20001",
        group_id="30001",
        chat_type="group",
        raw_message=raw_message,
        timestamp=datetime(2026, 6, 4, 12, 0),
        has_image=False,
        has_forward=False,
        forward_messages=[],
    )


def test_track_reply_returns_root_and_messages():
    async def _run():
        source = _message("m-current", "当前")
        quoted = _message("m-quote", "引用")
        plugin = SimpleNamespace(_bridge=_BridgeStub(source, chain=[quoted]))
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "track_reply"
        )

        result = await tool.handler(
            {"source_msg": source},
            {"max_depth": 4},
        )

        assert result.status == "ok"
        assert result.data["root_message_id"] == "m-quote"
        assert result.data["messages"][0]["raw_message"] == "引用"

    asyncio.run(_run())


def test_track_reply_empty_chain_is_non_retryable_failure():
    async def _run():
        source = _message("m-current", "当前")
        plugin = SimpleNamespace(_bridge=_BridgeStub(source, chain=[]))
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "track_reply"
        )

        result = await tool.handler(
            {"source_msg": source},
            {"max_depth": 4},
        )

        assert result.status == "failed"
        assert result.error_code == "reply_chain_not_found"
        assert result.retryable is False
        assert result.data["messages"] == []
        assert "不要再次调用 track_reply" in result.message

    asyncio.run(_run())


def test_load_context_returns_recent_window_messages():
    async def _run():
        source = _message("m-current", "当前")
        recent_a = _message("m-a", "A")
        recent_b = _message("m-b", "B")
        plugin = SimpleNamespace(
            _bridge=_BridgeStub(source, recent=[recent_a, recent_b])
        )
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "load_context"
        )

        result = await tool.handler(
            {"source_msg": source, "chat_type": "group", "chat_id": "30001"},
            {"limit": 2, "since_minutes": 30},
        )

        assert result.status == "ok"
        assert [item["message_id"] for item in result.data["messages"]] == [
            "m-a",
            "m-b",
        ]

    asyncio.run(_run())
