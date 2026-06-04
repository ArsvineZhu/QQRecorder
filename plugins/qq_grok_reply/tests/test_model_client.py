import asyncio
from types import SimpleNamespace

import pytest

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context import BuiltContext
from plugins.qq_grok_reply.llm import ReplyModelError, generate_reply


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

    result = asyncio.run(generate_reply(api, ctx, settings))

    assert result.text == "你好，世界"
    assert result.requested_more_context is False
    assert result.model_name == "demo"
    assert "当前消息" in result.model_request_summary
    assert "【当前消息】" in result.model_request_user_prompt
    assert "当前消息" in result.model_request_user_prompt
    assert result.model_response_summary == "你好，世界"


def test_generate_reply_returns_more_context_request_from_tool_call():
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
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="request_more_context",
                                        arguments='{"reason":"引用链里缺少前文"}',
                                    )
                                )
                            ]
                        )
                    )
                ],
            )
        )
    )
    ctx = BuiltContext(
        context_ids=["m-1"],
        quoted_block="",
        recent_block="",
        current_block="当前消息",
        variant="group_topic_local",
        chat_type="group",
    )

    result = asyncio.run(generate_reply(api, ctx, settings))

    assert result.text == ""
    assert result.requested_more_context is True
    assert result.request_reason == "引用链里缺少前文"
    assert "tools" in api.ai.calls[0][1]


def test_generate_reply_returns_more_context_request_from_function_call():
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
                function_call=SimpleNamespace(
                    name="request_more_context",
                    arguments='{"reason":"需要更大范围话题"}',
                ),
            )
        )
    )
    ctx = BuiltContext(
        context_ids=["m-1"],
        quoted_block="",
        recent_block="",
        current_block="当前消息",
        variant="private_topic_local",
        chat_type="private",
    )

    result = asyncio.run(generate_reply(api, ctx, settings))

    assert result.requested_more_context is True
    assert result.request_reason == "需要更大范围话题"


def test_generate_reply_second_pass_disables_more_context_tool():
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
                choices=[SimpleNamespace(message=SimpleNamespace(content="最终回复"))],
            )
        )
    )
    ctx = BuiltContext(
        context_ids=["m-1"],
        quoted_block="",
        recent_block="",
        current_block="当前消息",
        variant="group_topic_expanded",
        chat_type="group",
    )

    result = asyncio.run(generate_reply(api, ctx, settings, allow_more_context=False))

    assert result.text == "最终回复"
    assert result.requested_more_context is False
    assert "tools" not in api.ai.calls[0][1]


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
