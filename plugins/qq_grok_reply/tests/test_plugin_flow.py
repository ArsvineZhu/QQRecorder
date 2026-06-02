import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context_builder import BuiltContext
from plugins.qq_grok_reply.model_client import ReplyModelError
from plugins.qq_grok_reply.plugin import QQGrokReplyPlugin
from plugins.qq_grok_reply.sender import SendOutcome


class _FakeReply:
    def __init__(self, message_id: str):
        self.id = message_id


class _FakeMessage:
    def __init__(self, text: str, *, reply_ids: list[str] | None = None):
        self.text = text
        self._replies = [_FakeReply(message_id) for message_id in reply_ids or []]

    def is_at(self, _user_id: str) -> bool:
        return False

    def filter(self, cls):
        if getattr(cls, "__name__", "") == "Reply":
            return self._replies
        return []


class _FakeEvent:
    def __init__(
        self,
        *,
        chat_type: str,
        raw_message: str,
        group_id: str | None = None,
        reply_ids: list[str] | None = None,
    ):
        self.user_id = "20001"
        self.self_id = "10001"
        self.group_id = group_id
        self.raw_message = raw_message
        self.message = _FakeMessage(raw_message, reply_ids=reply_ids)
        self.message_id = "evt-1"
        self.time = 1_700_000_000
        self.chat_type = chat_type


class _FakeBridge:
    def __init__(self, source_msg):
        self.source_msg = source_msg
        self.closed = False

    async def wait_until_visible(self, *_args, **_kwargs):
        return self.source_msg

    async def close(self):
        self.closed = True


class _FakeTraceStore:
    def __init__(self, sent_message_ids: set[str] | None = None):
        self.inserted = []
        self.finished = []
        self.sent_message_ids = sent_message_ids or set()

    async def init_db(self):
        return None

    async def close(self):
        return None

    async def insert_trace(self, **kwargs):
        self.inserted.append(kwargs)
        return len(self.inserted)

    async def finish_trace(self, trace_id: int, **kwargs):
        self.finished.append((trace_id, kwargs))

    async def get_sent_message_ids(self, *_args, **_kwargs):
        return self.sent_message_ids


class _FakeQQAPI:
    def __init__(self):
        self.group_calls = []
        self.private_calls = []

    async def post_group_array_msg(self, group_id: str, message):
        self.group_calls.append((group_id, message))
        return SimpleNamespace(message_id="fallback-group-1")

    async def post_private_array_msg(self, user_id: str, message):
        self.private_calls.append((user_id, message))
        return SimpleNamespace(message_id="fallback-1")


def _make_plugin(settings, tmp_path: Path, bridge, trace_store):
    plugin = QQGrokReplyPlugin()
    plugin.settings = settings
    plugin.workspace = tmp_path
    plugin.api = cast(Any, SimpleNamespace(qq=_FakeQQAPI(), ai=SimpleNamespace()))
    plugin._bridge = bridge
    plugin._trace_store = trace_store
    return plugin


def test_plugin_handle_disabled_is_noop(tmp_path: Path):
    plugin = _make_plugin(
        build_config({"enabled": False}),
        tmp_path,
        _FakeBridge(source_msg=None),
        _FakeTraceStore(),
    )
    event = _FakeEvent(chat_type="private", raw_message="你好")

    asyncio.run(plugin._handle(event, "private"))

    trace_store = cast(_FakeTraceStore, plugin._trace_store)
    qq_api = cast(_FakeQQAPI, plugin.api.qq)
    assert trace_store.inserted == []
    assert qq_api.private_calls == []


def test_plugin_handle_success_updates_trace(tmp_path: Path, monkeypatch):
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"private": ["20001"]},
        }
    )
    source_msg = SimpleNamespace(
        id=11,
        message_id="evt-1",
        chat_type="private",
        group_id=None,
        user_id="20001",
        replies=[],
    )
    plugin = _make_plugin(
        settings, tmp_path, _FakeBridge(source_msg), _FakeTraceStore()
    )
    event = _FakeEvent(chat_type="private", raw_message="你好")

    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.build_context",
        lambda *_args, **_kwargs: BuiltContext(
            context_ids=["evt-1"],
            quoted_block="",
            recent_block="",
            current_block="你好",
            variant="private_contextual",
        ),
    )
    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.generate_reply",
        lambda *_args, **_kwargs: (
            "收到",
            {
                "model_name": "demo",
                "model_request_summary": "req",
                "model_response_summary": "resp",
            },
        ),
    )
    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.send_reply",
        lambda *_args, **_kwargs: SendOutcome(True, "bot-1", 1, None),
    )

    asyncio.run(plugin._handle(event, "private"))

    trace_store = cast(_FakeTraceStore, plugin._trace_store)
    assert trace_store.inserted[0]["source_message_id"] == "evt-1"
    assert trace_store.finished[0][1]["decision"] == "replied"
    assert trace_store.finished[0][1]["sent_message_id"] == "bot-1"


def test_plugin_handle_reply_to_bot_reaches_final_decision(tmp_path: Path, monkeypatch):
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
            "trigger": {"allow_reply_to_bot": True},
            "cooldown": {"group_chat_sec": 0, "group_user_sec": 0},
        }
    )
    source_msg = SimpleNamespace(
        id=11,
        message_id="evt-1",
        chat_type="group",
        group_id="30001",
        user_id="20001",
        replies=[SimpleNamespace(reply_to_message_id="bot-msg-1")],
    )
    plugin = _make_plugin(
        settings,
        tmp_path,
        _FakeBridge(source_msg),
        _FakeTraceStore(sent_message_ids={"bot-msg-1"}),
    )
    event = _FakeEvent(
        chat_type="group",
        raw_message="继续说",
        group_id="30001",
        reply_ids=["bot-msg-1"],
    )

    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.build_context",
        lambda *_args, **_kwargs: BuiltContext(
            context_ids=["evt-1"],
            quoted_block="",
            recent_block="",
            current_block="继续说",
            variant="group_compact",
        ),
    )
    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.generate_reply",
        lambda *_args, **_kwargs: (
            "继续",
            {
                "model_name": "demo",
                "model_request_summary": "req",
                "model_response_summary": "resp",
            },
        ),
    )
    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.send_reply",
        lambda *_args, **_kwargs: SendOutcome(True, "bot-msg-2", 1, None),
    )

    asyncio.run(plugin._handle(event, "group"))

    trace_store = cast(_FakeTraceStore, plugin._trace_store)
    assert trace_store.inserted[0]["trigger_reason"] == "reply_to_bot"
    assert trace_store.finished[0][1]["decision"] == "replied"


def test_plugin_handle_private_timeout_sends_fallback(tmp_path: Path, monkeypatch):
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"private": ["20001"]},
        }
    )
    source_msg = SimpleNamespace(
        id=11,
        message_id="evt-1",
        chat_type="private",
        group_id=None,
        user_id="20001",
        replies=[],
    )
    plugin = _make_plugin(
        settings, tmp_path, _FakeBridge(source_msg), _FakeTraceStore()
    )
    event = _FakeEvent(chat_type="private", raw_message="你好")

    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.build_context",
        lambda *_args, **_kwargs: BuiltContext(
            context_ids=["evt-1"],
            quoted_block="",
            recent_block="",
            current_block="你好",
            variant="private_contextual",
        ),
    )

    def _raise_timeout(*_args, **_kwargs):
        raise ReplyModelError("llm_timeout", "模型超时")

    monkeypatch.setattr("plugins.qq_grok_reply.plugin.generate_reply", _raise_timeout)

    asyncio.run(plugin._handle(event, "private"))

    qq_api = cast(_FakeQQAPI, plugin.api.qq)
    trace_store = cast(_FakeTraceStore, plugin._trace_store)
    assert qq_api.private_calls
    assert trace_store.finished[0][1]["decision"] == "error"
    assert trace_store.finished[0][1]["error_code"] == "llm_timeout"


def test_plugin_handle_group_prefix_timeout_sends_fallback(tmp_path: Path, monkeypatch):
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
        }
    )
    source_msg = SimpleNamespace(
        id=11,
        message_id="evt-1",
        chat_type="group",
        group_id="30001",
        user_id="20001",
        replies=[],
    )
    plugin = _make_plugin(
        settings, tmp_path, _FakeBridge(source_msg), _FakeTraceStore()
    )
    event = _FakeEvent(chat_type="group", raw_message="/ask 你好", group_id="30001")

    monkeypatch.setattr(
        "plugins.qq_grok_reply.plugin.build_context",
        lambda *_args, **_kwargs: BuiltContext(
            context_ids=["evt-1"],
            quoted_block="",
            recent_block="",
            current_block="你好",
            variant="group_compact",
        ),
    )

    def _raise_timeout(*_args, **_kwargs):
        raise ReplyModelError("llm_timeout", "模型超时")

    monkeypatch.setattr("plugins.qq_grok_reply.plugin.generate_reply", _raise_timeout)

    asyncio.run(plugin._handle(event, "group"))

    qq_api = cast(_FakeQQAPI, plugin.api.qq)
    trace_store = cast(_FakeTraceStore, plugin._trace_store)
    assert qq_api.group_calls
    assert trace_store.finished[0][1]["decision"] == "error"
    assert trace_store.finished[0][1]["error_code"] == "llm_timeout"
