import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context_builder import BuiltContext
from plugins.qq_grok_reply.model_client import ReplyModelError, generate_reply


class _FakeAIAPI:
    def __init__(self, response=None, delay: float = 0.0):
        self.response = response
        self.delay = delay
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.response


def test_generate_reply_returns_text_and_metadata():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "model": {"model": "demo"},
        }
    )
    api = SimpleNamespace(
        ai=_FakeAIAPI(
            response=SimpleNamespace(
                model="demo",
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="你好，世界"))
                ],
            )
        )
    )
    ctx = BuiltContext(
        context_ids=["m-1"],
        quoted_block="",
        recent_block="",
        current_block="当前消息",
        variant="private_contextual",
    )

    text, meta = asyncio.run(generate_reply(api, ctx, settings))

    assert text == "你好，世界"
    assert meta["model_name"] == "demo"
    assert "当前消息" in meta["model_request_summary"]
    assert meta["model_response_summary"] == "你好，世界"
    request_messages = cast(list[dict[str, str]], meta["request_messages"])
    assert request_messages[0]["role"] == "system"
    assert request_messages[1]["content"]
    assert meta["response_text"] == "你好，世界"


def test_generate_reply_raises_timeout_error():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "model": {"timeout_sec": 1},
        }
    )
    api = SimpleNamespace(
        ai=_FakeAIAPI(
            response=SimpleNamespace(
                model="demo",
                choices=[SimpleNamespace(message=SimpleNamespace(content="不会返回"))],
            ),
            delay=1.2,
        )
    )
    ctx = BuiltContext(
        context_ids=["m-1"],
        quoted_block="",
        recent_block="",
        current_block="当前消息",
        variant="group_compact",
    )

    with pytest.raises(ReplyModelError, match="llm_timeout"):
        asyncio.run(generate_reply(api, ctx, settings))
