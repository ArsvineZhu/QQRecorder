import asyncio
from types import SimpleNamespace

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.sender import send_reply


class _FakeQQAPI:
    def __init__(self, *, fail_after: int | None = None):
        self.fail_after = fail_after
        self.group_calls = []
        self.private_calls = []

    async def send_group_msg(self, group_id: str, message):
        self.group_calls.append((group_id, message))
        if self.fail_after is not None and len(self.group_calls) > self.fail_after:
            raise RuntimeError("send failed")
        return SimpleNamespace(message_id=f"group-{len(self.group_calls)}")

    async def send_private_msg(self, user_id: str, message):
        self.private_calls.append((user_id, message))
        if self.fail_after is not None and len(self.private_calls) > self.fail_after:
            raise RuntimeError("send failed")
        return SimpleNamespace(message_id=f"private-{len(self.private_calls)}")


class _FakeEvent:
    def __init__(
        self, *, group_id: str | None, user_id: str, message_id: str = "src-1"
    ):
        self.group_id = group_id
        self.user_id = user_id
        self.message_id = message_id


def test_send_reply_splits_group_text_and_records_first_message_id():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "send": {"group_max_chars_per_part": 8, "group_max_parts": 2},
        }
    )
    api = SimpleNamespace(qq=_FakeQQAPI())
    event = _FakeEvent(group_id="30001", user_id="20001")

    outcome = asyncio.run(
        send_reply(api, event, "第一句很短。第二句也很短。", settings)
    )

    assert outcome.sent is True
    assert outcome.sent_message_id == "group-1"
    assert outcome.sent_parts == 2
    first_payload = api.qq.group_calls[0][1]
    assert first_payload[0]["type"] == "reply"


def test_send_reply_reports_partial_send_error():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "send": {"private_max_chars_per_part": 5, "private_max_parts": 2},
        }
    )
    api = SimpleNamespace(qq=_FakeQQAPI(fail_after=1))
    event = _FakeEvent(group_id=None, user_id="20001")

    outcome = asyncio.run(send_reply(api, event, "甲乙丙丁戊己庚辛", settings))

    assert outcome.sent is False
    assert outcome.sent_message_id == "private-1"
    assert outcome.sent_parts == 1
    assert outcome.error_code == "partial_send"
