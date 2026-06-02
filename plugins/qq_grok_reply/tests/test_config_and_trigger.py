from types import SimpleNamespace

import pytest

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.trigger import (
    CooldownTracker,
    final_decision,
    prefilter_event,
)


class _FakeReply:
    def __init__(self, message_id: str):
        self.id = message_id


class _FakeAt:
    def __init__(self, user_id: str):
        self.user_id = user_id


class _FakeMessage:
    def __init__(
        self,
        text: str = "",
        *,
        at_ids: list[str] | None = None,
        reply_ids: list[str] | None = None,
    ):
        self.text = text
        self._ats = [_FakeAt(user_id) for user_id in at_ids or []]
        self._replies = [_FakeReply(message_id) for message_id in reply_ids or []]

    def is_at(self, user_id: str) -> bool:
        return user_id in {item.user_id for item in self._ats}

    def filter(self, cls):
        name = getattr(cls, "__name__", "")
        if name == "Reply":
            return self._replies
        if name == "At":
            return self._ats
        return []


class _FakeEvent:
    def __init__(
        self,
        *,
        chat_type: str,
        user_id: str = "20001",
        self_id: str = "10001",
        group_id: str | None = None,
        raw_message: str = "",
        message: _FakeMessage | None = None,
    ):
        self.user_id = user_id
        self.self_id = self_id
        self.group_id = group_id
        self.raw_message = raw_message
        self.message = message or _FakeMessage(raw_message)
        self.message_id = "evt-1"
        self.time = 1_700_000_000
        self.chat_type = chat_type


def test_build_config_requires_recorder_db_when_enabled():
    with pytest.raises(ValueError, match="recorder_db"):
        build_config({"enabled": True})


def test_prefilter_private_message_uses_private_default():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"private": ["20001"]},
        }
    )
    event = _FakeEvent(chat_type="private", raw_message="你好")

    assert prefilter_event(event, settings) == "private_default"


def test_prefilter_group_plain_message_is_skipped():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
        }
    )
    event = _FakeEvent(
        chat_type="group",
        group_id="30001",
        raw_message="普通聊天",
        message=_FakeMessage("普通聊天"),
    )

    assert prefilter_event(event, settings) is None


def test_prefilter_group_at_bot_triggers():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
        }
    )
    event = _FakeEvent(
        chat_type="group",
        group_id="30001",
        raw_message="@bot 你好",
        message=_FakeMessage("@bot 你好", at_ids=["10001"]),
    )

    assert prefilter_event(event, settings) == "group_at_bot"


def test_prefilter_ignores_recorder_command_and_self_messages():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
        }
    )
    command_event = _FakeEvent(
        chat_type="group",
        group_id="30001",
        raw_message="/recorder recent",
        message=_FakeMessage("/recorder recent"),
    )
    self_event = _FakeEvent(
        chat_type="group",
        group_id="30001",
        user_id="10001",
        raw_message="/ask ping",
        message=_FakeMessage("/ask ping"),
    )

    assert prefilter_event(command_event, settings) is None
    assert prefilter_event(self_event, settings) is None


def test_final_decision_handles_missing_row_and_cooldown():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
        }
    )
    event = _FakeEvent(
        chat_type="group",
        group_id="30001",
        raw_message="@bot 你好",
        message=_FakeMessage("@bot 你好", at_ids=["10001"]),
    )
    tracker = CooldownTracker()

    allowed, reason = final_decision(
        event,
        source_msg=None,
        prefilter_reason="group_at_bot",
        settings=settings,
        cooldowns=tracker,
    )
    assert allowed is False
    assert reason == "missing_recorder_row"

    source_msg = SimpleNamespace(
        message_id="evt-1",
        chat_type="group",
        group_id="30001",
        user_id="20001",
        replies=[],
    )
    allowed, reason = final_decision(
        event,
        source_msg=source_msg,
        prefilter_reason="group_at_bot",
        settings=settings,
        cooldowns=tracker,
    )
    assert allowed is True
    assert reason == "group_at_bot"

    allowed, reason = final_decision(
        event,
        source_msg=source_msg,
        prefilter_reason="group_at_bot",
        settings=settings,
        cooldowns=tracker,
    )
    assert allowed is False
    assert reason == "cooldown"


def test_final_decision_allows_reply_to_bot_when_enabled():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": False,
            "targets": {"groups": ["30001"]},
            "trigger": {"allow_reply_to_bot": True},
        }
    )
    event = _FakeEvent(
        chat_type="group",
        group_id="30001",
        raw_message="跟进问题",
        message=_FakeMessage("跟进问题", reply_ids=["bot-msg-1"]),
    )
    source_msg = SimpleNamespace(
        message_id="evt-1",
        chat_type="group",
        group_id="30001",
        user_id="20001",
        replies=[SimpleNamespace(reply_to_message_id="bot-msg-1")],
    )

    allowed, reason = final_decision(
        event,
        source_msg=source_msg,
        prefilter_reason=None,
        settings=settings,
        cooldowns=CooldownTracker(),
        bot_reply_message_ids={"bot-msg-1"},
    )

    assert allowed is True
    assert reason == "reply_to_bot"
