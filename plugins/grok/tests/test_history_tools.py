import asyncio
from datetime import datetime
from types import SimpleNamespace

from plugins.grok.tools.history_tools import build_history_tools


class _BridgeStub:
    def __init__(self):
        self.calls = []

    async def query_chat_history(self, **kwargs):
        self.calls.append(kwargs)
        return [
            SimpleNamespace(
                message_id="m-1",
                chat_type=kwargs["chat_type"],
                group_id=kwargs["chat_id"] if kwargs["chat_type"] == "group" else "",
                user_id=kwargs.get("user_id") or "3980072605",
                sender_nickname="阿梓",
                sender_card="",
                timestamp="2026-06-06 15:30:00",
                raw_message="关于辩论的发言",
                has_forward=True,
                has_image=False,
                has_reply=False,
                has_video=False,
                has_at=False,
                has_app_share=False,
            )
        ]


def _source():
    return SimpleNamespace(
        message_id="m-current",
        user_id="3980072605",
        sender_nickname="阿梓",
        sender_card="",
        group_id="1101497265",
        chat_type="group",
        raw_message="帮我查一下",
        timestamp=datetime(2026, 6, 6, 16, 0, 0),
    )


def test_query_chat_history_defaults_to_current_chat_scope():
    async def _run():
        bridge = _BridgeStub()
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item
            for item in build_history_tools(plugin)
            if item.name == "query_chat_history"
        )

        result = await tool.handler(
            {
                "source_msg": _source(),
                "chat_type": "group",
                "chat_id": "1101497265",
                "user_id": "3980072605",
            },
            {"keyword": "辩论", "limit": 5, "order": "asc"},
        )

        assert result.status == "ok"
        assert result.data["total_returned"] == 1
        assert result.data["messages"][0]["message_id"] == "m-1"
        assert bridge.calls[0]["chat_type"] == "group"
        assert bridge.calls[0]["chat_id"] == "1101497265"
        assert bridge.calls[0]["keyword"] == "辩论"
        assert bridge.calls[0]["order"] == "asc"

    asyncio.run(_run())


def test_query_chat_history_rejects_empty_filters_and_redirects_to_load_context():
    async def _run():
        bridge = _BridgeStub()
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item
            for item in build_history_tools(plugin)
            if item.name == "query_chat_history"
        )

        result = await tool.handler(
            {
                "source_msg": _source(),
                "chat_type": "group",
                "chat_id": "1101497265",
                "user_id": "3980072605",
            },
            {},
        )

        assert result.status == "failed"
        assert result.error_code == "empty_history_query"
        assert "load_context" in result.message

    asyncio.run(_run())


def test_query_chat_history_requires_chat_type_when_chat_id_is_explicit():
    async def _run():
        bridge = _BridgeStub()
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item
            for item in build_history_tools(plugin)
            if item.name == "query_chat_history"
        )

        result = await tool.handler(
            {
                "source_msg": _source(),
                "chat_type": "group",
                "chat_id": "1101497265",
                "user_id": "3980072605",
            },
            {"chat_id": "22002200", "keyword": "辩论"},
        )

        assert result.status == "failed"
        assert result.error_code == "chat_type_required"

    asyncio.run(_run())


def test_query_chat_history_rejects_invalid_time_filters():
    async def _run():
        bridge = _BridgeStub()
        plugin = SimpleNamespace(_bridge=bridge)
        tool = next(
            item
            for item in build_history_tools(plugin)
            if item.name == "query_chat_history"
        )

        result = await tool.handler(
            {
                "source_msg": _source(),
                "chat_type": "group",
                "chat_id": "1101497265",
                "user_id": "3980072605",
            },
            {"keyword": "辩论", "time_from": "not-a-time"},
        )

        assert result.status == "failed"
        assert result.error_code == "invalid_time_filter"

    asyncio.run(_run())
