import asyncio
from datetime import datetime
from types import SimpleNamespace

from plugins.grok.tools.context_tools import build_context_tools


class _BridgeStub:
    def __init__(
        self,
        source,
        chain=None,
        recent=None,
        around=None,
        forward=None,
        analysis_map=None,
    ):
        self.source = source
        self.chain = chain or []
        self.recent = recent or []
        self.around = around or []
        self.forward = forward or []
        self.analysis_map = analysis_map or {}
        self.calls = []
        self.backfills = []

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
        self.calls.append(("recent", limit, since_minutes, before_or_at))
        assert since_minutes == 30
        assert before_or_at == self.source.timestamp
        return self.recent[:limit]

    async def get_neighbors(
        self,
        _chat_type: str,
        _chat_id: str,
        *,
        anchor,
        before_limit: int,
        after_limit: int,
    ):
        self.calls.append(("around", anchor.message_id, before_limit, after_limit))
        return self.around

    async def get_after(self, anchor, limit: int, since_minutes=None):
        self.calls.append(("forward", anchor.message_id, limit, since_minutes))
        return self.forward[:limit]

    async def get_image_analyses_by_message(self, message_db_id: int):
        return self.analysis_map.get(message_db_id, [])

    async def backfill_forward_messages(self, message_db_id: int, forward_messages):
        self.backfills.append((message_db_id, forward_messages))


def _message(message_id: str, raw_message: str):
    return SimpleNamespace(
        id=1,
        message_id=message_id,
        user_id="20001",
        sender_nickname="测试昵称",
        sender_card="",
        group_id="30001",
        chat_type="group",
        raw_message=raw_message,
        timestamp=datetime(2026, 6, 4, 12, 0),
        has_image=False,
        has_forward=False,
        forward_messages=[],
        images=[],
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
        assert result.data["messages"][0]["sender_nickname"] == "测试昵称"

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


def test_load_context_supports_around_anchor_by_message_id():
    async def _run():
        source = _message("m-current", "当前")
        anchor = _message("m-anchor", "锚点")
        before = _message("m-before", "前文")
        after = _message("m-after", "后文")
        bridge = _BridgeStub(source, around=[before, after])

        async def _get_message(message_id: str):
            if message_id == "m-anchor":
                return anchor
            return await _BridgeStub.get_message(bridge, message_id)

        bridge.get_message = _get_message
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "load_context"
        )

        result = await tool.handler(
            {"source_msg": source, "chat_type": "group", "chat_id": "30001"},
            {
                "anchor": "message_id",
                "message_id": "m-anchor",
                "direction": "around",
                "before": 2,
                "after": 2,
            },
        )

        assert result.status == "ok"
        assert result.data["anchor_message_id"] == "m-anchor"
        assert [item["message_id"] for item in result.data["messages"]] == [
            "m-before",
            "m-after",
        ]
        assert bridge.calls[0] == ("around", "m-anchor", 2, 2)

    asyncio.run(_run())


def test_load_context_supports_forward_direction():
    async def _run():
        source = _message("m-current", "当前")
        next_a = _message("m-next-a", "后文A")
        next_b = _message("m-next-b", "后文B")
        bridge = _BridgeStub(source, forward=[next_a, next_b])
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "load_context"
        )

        result = await tool.handler(
            {"source_msg": source, "chat_type": "group", "chat_id": "30001"},
            {
                "anchor": "current",
                "direction": "forward",
                "limit": 2,
            },
        )

        assert result.status == "ok"
        assert [item["message_id"] for item in result.data["messages"]] == [
            "m-next-a",
            "m-next-b",
        ]
        assert bridge.calls[0] == ("forward", "m-current", 2, None)

    asyncio.run(_run())


def test_load_context_payload_includes_forward_and_vision_previews():
    async def _run():
        source = _message("m-current", "当前")
        source.id = 10
        source.has_forward = True
        source.forward_messages = [
            SimpleNamespace(depth=0, nickname="阿梓", content_summary="转发摘要")
        ]
        source.has_image = True
        source.images = [SimpleNamespace(id=1)]
        bridge = _BridgeStub(
            source,
            recent=[source],
            analysis_map={
                10: [
                    SimpleNamespace(
                        semantic_text="图片里是一张截图，重点是进度异常",
                    )
                ]
            },
        )
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "load_context"
        )

        result = await tool.handler(
            {"source_msg": source, "chat_type": "group", "chat_id": "30001"},
            {
                "limit": 1,
                "since_minutes": 30,
                "include_forward_preview": True,
                "include_vision_preview": True,
            },
        )

        payload = result.data["messages"][0]
        assert payload["forward_count"] == 1
        assert payload["forward_preview"][0]["content_summary"] == "转发摘要"
        assert payload["image_count"] == 1
        assert payload["image_analysis_count"] == 1
        assert "进度异常" in payload["image_analysis_preview"][0]
        assert payload["image_analysis_status"] == "ready"

    asyncio.run(_run())


def test_load_message_returns_single_message_payload():
    async def _run():
        source = _message("m-current", "当前")
        plugin = SimpleNamespace(_bridge=_BridgeStub(source))
        tool = next(
            item for item in build_context_tools(plugin) if item.name == "load_message"
        )

        result = await tool.handler(
            {"source_msg": source},
            {"message_id": "m-current"},
        )

        assert result.status == "ok"
        assert result.data["message"]["message_id"] == "m-current"
        assert result.data["message"]["raw_message"] == "当前"
        assert result.data["message"]["sender_nickname"] == "测试昵称"

    asyncio.run(_run())


def test_extract_forward_uses_api_fallback_and_backfills_db():
    async def _run():
        source = _message("m-current", "[CQ:forward,id=fwd-1]")
        source.id = 10
        source.forward_messages = []
        bridge = _BridgeStub(source)

        async def _get_forward_msg(forward_id):
            assert forward_id == "fwd-1"
            return {
                "messages": [
                    {
                        "sender": {"user_id": "20001", "nickname": "阿梓"},
                        "content": [{"type": "text", "data": {"text": "转发正文"}}],
                    }
                ]
            }

        plugin = SimpleNamespace(
            _bridge=bridge,
            api=SimpleNamespace(
                qq=SimpleNamespace(
                    query=SimpleNamespace(get_forward_msg=_get_forward_msg)
                )
            ),
        )
        tool = next(
            item
            for item in build_context_tools(plugin)
            if item.name == "extract_forward"
        )

        result = await tool.handler(
            {"source_msg": source},
            {"message_id": "m-current"},
        )

        assert result.status == "ok"
        assert result.data["source"] == "api_fallback"
        assert result.data["forward_messages"][0]["nickname"] == "阿梓"
        assert bridge.backfills[0][0] == 10

    asyncio.run(_run())
