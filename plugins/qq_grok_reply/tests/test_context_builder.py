import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context_builder import TopicContextError, build_context


class _BridgeStub:
    def __init__(self, quote_message, recent_messages):
        self.quote_message = quote_message
        self.recent_messages = recent_messages

    async def get_message(self, _message_id: str):
        return self.quote_message

    async def get_recent(self, _chat_type: str, _chat_id: str, _limit: int):
        return self.recent_messages

    async def get_candidates(self, _chat_type: str, _chat_id: str, **_kwargs):
        return self.recent_messages


class _FakeAIAPI:
    def __init__(self, tool_arguments: str):
        self.tool_arguments = tool_arguments
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="submit_topic_analysis",
                                    arguments=self.tool_arguments,
                                )
                            )
                        ]
                    )
                )
            ]
        )


class _FakeRuntimeAPI:
    class qq:
        class query:
            @staticmethod
            async def get_forward_msg(_forward_id: str):
                return {
                    "messages": [
                        {
                            "type": "node",
                            "data": {
                                "user_id": "30001",
                                "nickname": "甲",
                                "content": [
                                    {"type": "text", "data": {"text": "第一条转发内容"}}
                                ],
                            },
                        },
                        {
                            "type": "node",
                            "data": {
                                "user_id": "30002",
                                "nickname": "乙",
                                "content": [
                                    {"type": "text", "data": {"text": "第二条转发内容"}}
                                ],
                            },
                        },
                    ]
                }


def _message(
    message_id: str,
    *,
    raw_message: str,
    chat_type: str = "group",
    user_id: str = "20001",
    group_id: str | None = "30001",
    has_image: bool = False,
    has_forward: bool = False,
    has_reply: bool = False,
    has_app_share: bool = False,
    app_share_title: str = "",
    app_share_name: str = "",
    reply_to: str | None = None,
    timestamp: datetime = datetime(2024, 6, 2, 12, 30),
    sender_nickname: str | None = None,
    sender_card: str | None = None,
    forward_messages=None,
):
    replies = []
    if reply_to:
        replies.append(SimpleNamespace(reply_to_message_id=reply_to))
    app_shares = []
    if has_app_share:
        app_shares.append(
            SimpleNamespace(title=app_share_title, app_name=app_share_name)
        )
    return SimpleNamespace(
        message_id=message_id,
        timestamp=timestamp,
        raw_message=raw_message,
        chat_type=chat_type,
        user_id=user_id,
        group_id=group_id,
        has_image=has_image,
        has_forward=has_forward,
        has_reply=has_reply,
        has_app_share=has_app_share,
        app_shares=app_shares,
        replies=replies,
        sender_nickname=sender_nickname,
        sender_card=sender_card,
        forward_messages=forward_messages or [],
    )


def test_build_context_unescapes_text_and_collects_context_ids():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"recent_limit_group": 3},
        }
    )
    source = _message(
        "m-current",
        raw_message="当前\\n消息",
        reply_to="m-quote",
        sender_card="Arsvine",
    )
    quote = _message("m-quote", raw_message="引用\\n内容", sender_nickname="小明")
    recent = [
        source,
        _message("m-image", raw_message="", has_image=True, sender_nickname="图图"),
        _message(
            "m-forward", raw_message="", has_forward=True, sender_nickname="转发者"
        ),
    ]

    event = SimpleNamespace(raw_message="/ask 当前\n消息", user_id="20001")
    built = asyncio.run(
        build_context(
            source,
            _BridgeStub(quote, recent),
            settings,
            event=event,
            trigger_reason="prefix",
            sender_name="Arsvine",
        )
    )

    assert built.variant == "group_compact"
    assert built.context_ids == ["m-current", "m-quote", "m-image", "m-forward"]
    assert "[12:30] Arsvine: 当前\n消息" in built.current_block
    assert "[12:30] 小明: 引用\n内容" in built.quoted_block
    assert "[12:30] 图图: [图片]" in built.recent_block
    assert "[12:30] 转发者: [合并转发]" in built.recent_block
    assert built.max_reply_chars == 500


def test_build_context_quote_forward_prefers_forward_summary_over_cq_code():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {
                "quote_chars_group": 300,
                "forward_max_items": 2,
                "forward_max_chars": 160,
            },
        }
    )
    source = _message(
        "m-current",
        raw_message="评价一下",
        reply_to="m-forward-quote",
        sender_card="Arsvine",
    )
    quote = _message(
        "m-forward-quote",
        raw_message="[CQ:forward,id=123456,content=foo]",
        has_forward=True,
        sender_nickname="转发者",
        forward_messages=[
            SimpleNamespace(id=1, depth=0, nickname="A", content_summary="第一条观点"),
            SimpleNamespace(id=2, depth=0, nickname="B", content_summary="第二条观点"),
        ],
    )

    built = asyncio.run(build_context(source, _BridgeStub(quote, [source]), settings))

    assert "[CQ:forward" not in built.quoted_block
    assert "[12:30] 转发者: [合并转发]" in built.quoted_block
    assert "合并转发摘要" in built.quoted_block
    assert "A：第一条观点" in built.quoted_block


def test_build_context_quote_legacy_forward_cq_renders_forward_placeholder():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    source = _message(
        "m-current",
        raw_message="能看到吗",
        chat_type="private",
        group_id=None,
        reply_to="m-legacy-forward",
    )
    quote = _message(
        "m-legacy-forward",
        raw_message="[CQ:forward,id=123456,content=foo]",
        chat_type="private",
        group_id=None,
        has_forward=False,
        sender_nickname="Zodiac",
    )

    built = asyncio.run(build_context(source, _BridgeStub(quote, [source]), settings))

    assert built.quoted_block == "[12:30] Zodiac: [合并转发]"


def test_legacy_forward_quote_fetches_summary_when_api_available():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"forward_max_items": 2, "forward_max_chars": 200},
        }
    )
    source = _message(
        "m-current",
        raw_message="这个你怎么看",
        chat_type="private",
        group_id=None,
        reply_to="m-legacy-forward",
    )
    quote = _message(
        "m-legacy-forward",
        raw_message="[CQ:forward,id=123456,content=foo]",
        chat_type="private",
        group_id=None,
        has_forward=False,
        sender_nickname="Zodiac",
    )

    built = asyncio.run(
        build_context(
            source,
            _BridgeStub(quote, [source]),
            settings,
            runtime_api=_FakeRuntimeAPI(),
        )
    )

    assert "[12:30] Zodiac: [合并转发]" in built.quoted_block
    assert "合并转发摘要" in built.quoted_block
    assert "甲：第一条转发内容" in built.quoted_block


def test_build_context_respects_private_budget_and_recent_limit():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {
                "recent_limit_private": 2,
                "total_chars_private": 60,
                "quote_chars_private": 20,
            },
        }
    )
    source = _message(
        "m-private",
        chat_type="private",
        group_id=None,
        raw_message="这是当前消息" * 5,
        reply_to="m-quote",
    )
    quote = _message(
        "m-quote",
        chat_type="private",
        group_id=None,
        raw_message="引用消息" * 5,
    )
    recent = [
        source,
        _message(
            "m-r1", chat_type="private", group_id=None, raw_message="最近消息一" * 5
        ),
        _message(
            "m-r2", chat_type="private", group_id=None, raw_message="最近消息二" * 5
        ),
        _message(
            "m-r3", chat_type="private", group_id=None, raw_message="最近消息三" * 5
        ),
    ]

    built = asyncio.run(build_context(source, _BridgeStub(quote, recent), settings))

    assert built.variant == "private_contextual"
    assert "m-r3" not in built.context_ids
    assert len(built.current_block) <= 60
    assert len(built.quoted_block) <= 20


def test_build_context_recent_messages_are_chronological():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"mode": "recent", "recent_limit_group": 3},
        }
    )
    source = _message(
        "m-current",
        raw_message="当前",
        timestamp=datetime(2024, 6, 2, 12, 30),
    )
    older = _message(
        "m-older",
        raw_message="较早",
        timestamp=datetime(2024, 6, 2, 12, 27),
    )
    middle = _message(
        "m-middle",
        raw_message="中间",
        timestamp=datetime(2024, 6, 2, 12, 28),
    )
    newer = _message(
        "m-newer",
        raw_message="较新",
        timestamp=datetime(2024, 6, 2, 12, 29),
    )

    built = asyncio.run(
        build_context(
            source, _BridgeStub(None, [source, newer, middle, older]), settings
        )
    )

    assert built.context_ids == ["m-current", "m-older", "m-middle", "m-newer"]
    assert built.recent_block.index("[12:27]") < built.recent_block.index("[12:28]")
    assert built.recent_block.index("[12:28]") < built.recent_block.index("[12:29]")


def test_build_context_renders_share_placeholder_with_title_or_app_name():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    source = _message(
        "m-current",
        raw_message="看这个",
        has_app_share=True,
        app_share_title="阶段一设计",
        sender_card="Arsvine",
    )
    recent = [
        source,
        _message(
            "m-share",
            raw_message="",
            has_app_share=True,
            app_share_name="B站",
            sender_nickname="分享者",
        ),
    ]

    built = asyncio.run(
        build_context(
            source, _BridgeStub(None, recent), settings, sender_name="Arsvine"
        )
    )

    assert "[12:30] Arsvine: 看这个 [分享: 阶段一设计]" == built.current_block
    assert "[12:30] 分享者: [分享: B站]" == built.recent_block


def test_build_context_topic_ai_selects_related_messages_and_forward_summary():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {
                "mode": "topic_ai",
                "recent_chars_group": 500,
                "forward_max_items": 2,
                "forward_max_chars": 120,
            },
        }
    )
    source = _message("m-current", raw_message="这个转发里说的是硬盘吗")
    forward = _message(
        "m-forward",
        raw_message="看这个",
        has_forward=True,
        sender_nickname="转发者",
        forward_messages=[
            SimpleNamespace(
                id=1, depth=0, nickname="A", content_summary="讨论了外接硬盘价格"
            ),
            SimpleNamespace(
                id=2, depth=0, nickname="B", content_summary="提到 1TB 和 2TB 选择"
            ),
            SimpleNamespace(
                id=3, depth=0, nickname="C", content_summary="补充游戏安装速度问题"
            ),
        ],
    )
    noise = _message("m-noise", raw_message="中午吃什么", sender_nickname="路人")
    api = SimpleNamespace(
        ai=_FakeAIAPI(
            '{"topic_title":"硬盘选择","topic_summary":"大家在看转发里的硬盘容量和速度讨论",'
            '"participants":[{"name":"转发者","role":"提供转发"}],"selected_message_ids":["m-forward","m-current"],'
            '"excluded_message_ids":[{"id":"m-noise","reason":"午饭闲聊"}],"confidence":0.82,'
            '"needs_more_context":false,"error_code":""}'
        )
    )

    built = asyncio.run(
        build_context(
            source,
            _BridgeStub(None, [source, forward, noise]),
            settings,
            analyzer_api=api,
        )
    )

    assert "tools" in api.ai.calls[0][1]
    assert (
        api.ai.calls[0][1]["tool_choice"]["function"]["name"] == "submit_topic_analysis"
    )
    assert built.variant == "group_topic_ai"
    assert built.topic_title == "硬盘选择"
    assert built.topic_confidence == 0.82
    assert built.topic_participants == ["转发者（提供转发）"]
    assert built.context_ids == ["m-current", "m-forward"]
    assert "合并转发摘要" in built.recent_block
    assert "A：讨论了外接硬盘价格" in built.recent_block
    assert "……已截断。" in built.recent_block
    assert "m-noise" not in built.context_ids


def test_build_context_topic_ai_invalid_json_falls_back_to_recent():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"mode": "topic_ai", "fallback_recent_limit_group": 2},
        }
    )
    source = _message("m-current", raw_message="现在聊什么")
    recent = [
        source,
        _message("m-r1", raw_message="话题一"),
        _message("m-r2", raw_message="话题二"),
    ]
    api = SimpleNamespace(ai=_FakeAIAPI("不是 JSON"))

    built = asyncio.run(
        build_context(source, _BridgeStub(None, recent), settings, analyzer_api=api)
    )

    assert built.variant == "group_compact"
    assert built.topic_fallback_used is True
    assert built.topic_error_code == "topic_invalid_tool_arguments"
    assert built.context_ids == ["m-current", "m-r1", "m-r2"]


def test_build_context_topic_ai_invalid_json_raises_when_fallback_disabled():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"mode": "topic_ai", "fallback_recent_limit_group": 2},
            "topic_analyzer": {"fallback_to_recent": False},
        }
    )
    source = _message("m-current", raw_message="现在聊什么")
    recent = [
        source,
        _message("m-r1", raw_message="话题一"),
        _message("m-r2", raw_message="话题二"),
    ]
    api = SimpleNamespace(ai=_FakeAIAPI("不是 JSON"))

    with pytest.raises(TopicContextError) as exc_info:
        asyncio.run(
            build_context(source, _BridgeStub(None, recent), settings, analyzer_api=api)
        )

    assert exc_info.value.analysis.error_code == "topic_invalid_tool_arguments"
