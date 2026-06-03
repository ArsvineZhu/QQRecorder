import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context_builder import (
    BuiltContext,
    TopicContextError,
    build_context,
    expand_context,
)


class _BridgeStub:
    def __init__(
        self,
        quote_message,
        recent_messages,
        *,
        messages_by_id=None,
        reply_chain=None,
        neighbor_map=None,
        candidate_messages=None,
    ):
        self.quote_message = quote_message
        self.recent_messages = recent_messages
        self.messages_by_id = messages_by_id or {}
        self.reply_chain = reply_chain or []
        self.neighbor_map = neighbor_map or {}
        self.candidate_messages = candidate_messages or recent_messages

    async def get_message(self, _message_id: str):
        return self.messages_by_id.get(_message_id, self.quote_message)

    async def get_recent(self, _chat_type: str, _chat_id: str, _limit: int):
        return self.recent_messages

    async def get_recent_window(self, _chat_type: str, _chat_id: str, **_kwargs):
        return self.recent_messages

    async def get_candidates(self, _chat_type: str, _chat_id: str, **_kwargs):
        return self.candidate_messages

    async def get_reply_chain(self, _source_msg, *, max_depth: int):
        return self.reply_chain[:max_depth]

    async def get_neighbors(
        self,
        _chat_type: str,
        _chat_id: str,
        *,
        anchor,
        before_limit: int,
        after_limit: int,
    ):
        items = list(self.neighbor_map.get(str(anchor.message_id), []))
        return items[: before_limit + after_limit]


class _FakeAIAPI:
    def __init__(self, tool_arguments: str):
        self.tool_arguments = tool_arguments
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.tool_arguments))
            ]
        )


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
    segments=None,
    images=None,
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
        segments=segments or [],
        images=images or [],
    )


def _segment(segment_type: str, data: dict, order: int):
    return SimpleNamespace(
        segment_type=segment_type,
        segment_data=json.dumps(data, ensure_ascii=False),
        segment_order=order,
    )


def test_build_context_unescapes_text_and_collects_context_ids():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"mode": "recent", "recent_limit_group": 3},
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
        _message(
            "m-image",
            raw_message="",
            has_image=True,
            sender_nickname="图图",
            segments=[_segment("image", {"url": "https://example.com/a.png"}, 0)],
            images=[
                SimpleNamespace(
                    file_size=0,
                    width=320,
                    height=240,
                    downloaded=False,
                    is_sticker=False,
                    file_url="https://example.com/a.png",
                )
            ],
        ),
        _message(
            "m-forward",
            raw_message="",
            has_forward=True,
            sender_nickname="转发者",
            segments=[_segment("forward", {"id": "fw-1"}, 0)],
            forward_messages=[
                SimpleNamespace(
                    id=1, depth=0, nickname="A", content_summary="转发里的第一句"
                )
            ],
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
    assert "[12:30] 图图: [图片: 320x240" in built.recent_block
    assert "[12:30] 转发者: 合并转发摘要：" in built.recent_block
    assert "A：转发里的第一句" in built.recent_block
    assert built.max_reply_chars == 500


def test_build_context_respects_private_budget_and_recent_limit():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {
                "recent_limit_private": 2,
                "total_chars_private": 60,
                "quote_chars_private": 20,
                "mode": "recent",
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


def test_build_context_topic_ai_uses_local_window_and_quote_neighbors_only():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {
                "mode": "topic_ai",
                "local_recent_limit_group": 30,
                "local_recent_time_window_minutes_group": 30,
                "quote_chain_max_depth_group": 10,
                "quote_neighbor_limit_group": 2,
                "recent_chars_group": 500,
            },
        }
    )
    source = _message(
        "m-current",
        raw_message="我是在追问这个报价吗",
        reply_to="m-q2",
        timestamp=datetime(2024, 6, 2, 12, 30),
    )
    quote_1 = _message(
        "m-q1",
        raw_message="最早的报价",
        timestamp=datetime(2024, 6, 2, 12, 20),
    )
    quote_2 = _message(
        "m-q2",
        raw_message="上一条追问",
        reply_to="m-q1",
        timestamp=datetime(2024, 6, 2, 12, 25),
    )
    before = _message(
        "m-before",
        raw_message="补充背景",
        timestamp=datetime(2024, 6, 2, 12, 19),
    )
    after = _message(
        "m-after",
        raw_message="继续展开",
        timestamp=datetime(2024, 6, 2, 12, 26),
    )
    recent = [
        source,
        _message("m-r2", raw_message="最近两", timestamp=datetime(2024, 6, 2, 12, 29)),
        _message("m-r1", raw_message="最近一", timestamp=datetime(2024, 6, 2, 12, 28)),
    ]
    api = SimpleNamespace(ai=_FakeAIAPI('{"ignored":true}'))

    built = asyncio.run(
        build_context(
            source,
            _BridgeStub(
                quote_2,
                recent,
                messages_by_id={"m-q1": quote_1, "m-q2": quote_2},
                reply_chain=[quote_2, quote_1],
                neighbor_map={"m-q1": [before], "m-q2": [after]},
            ),
            settings,
            analyzer_api=api,
        )
    )

    assert api.ai.calls == []
    assert built.variant == "group_topic_local"
    assert built.topic_summary == ""
    assert built.context_ids == [
        "m-current",
        "m-q2",
        "m-q1",
        "m-before",
        "m-after",
        "m-r1",
        "m-r2",
    ]
    assert built.recent_block.index("[12:19]") < built.recent_block.index("[12:26]")
    assert built.recent_block.index("[12:26]") < built.recent_block.index("[12:28]")


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
        segments=[
            _segment("text", {"text": "看这个"}, 0),
            _segment("json", {"data": '{"desc":"QQ卡片"}'}, 1),
        ],
    )
    recent = [
        source,
        _message(
            "m-share",
            raw_message="",
            has_app_share=True,
            app_share_name="B站",
            sender_nickname="分享者",
            segments=[_segment("json", {"data": '{"desc":"QQ卡片"}'}, 0)],
        ),
    ]

    built = asyncio.run(
        build_context(
            source, _BridgeStub(None, recent), settings, sender_name="Arsvine"
        )
    )

    assert built.current_block == "[12:30] Arsvine: 看这个 阶段一设计"
    assert built.recent_block == "[12:30] 分享者: B站"


def test_build_context_current_block_strips_prefix_and_keeps_structured_segments():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"mode": "recent", "recent_limit_group": 1},
        }
    )
    source = _message(
        "m-current",
        raw_message="/ask 看这个",
        has_app_share=True,
        segments=[
            _segment("text", {"text": "/ask 看这个"}, 0),
            _segment("json", {"data": '{"desc":"QQ卡片"}'}, 1),
        ],
        app_share_title="阶段一设计",
        sender_card="Arsvine",
    )

    built = asyncio.run(
        build_context(
            source,
            _BridgeStub(None, [source]),
            settings,
            event=SimpleNamespace(raw_message="/ask 看这个", user_id="20001"),
            trigger_reason="prefix:/ask",
            sender_name="Arsvine",
        )
    )

    assert "/ask" not in built.current_block
    assert "看这个 阶段一设计" in built.current_block


def test_expand_context_merges_local_context_with_topic_selection():
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
    quote = _message("m-quote", raw_message="我们是在比较容量和速度")
    forward = _message(
        "m-forward",
        raw_message="看这个",
        has_forward=True,
        sender_nickname="转发者",
        segments=[_segment("forward", {"id": "fw-1"}, 0)],
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

    local_ctx = BuiltContext(
        context_ids=["m-current", "m-quote", "m-noise"],
        quoted_block="[12:29] A: 我们是在比较容量和速度",
        recent_block="[12:28] 路人: 中午吃什么",
        current_block="[12:30] 20001: 这个转发里说的是硬盘吗",
        variant="group_topic_local",
        chat_type="group",
    )

    built = asyncio.run(
        expand_context(
            source,
            local_ctx,
            _BridgeStub(
                quote,
                [source, forward, noise],
                messages_by_id={"m-quote": quote},
                candidate_messages=[source, quote, forward, noise],
            ),
            settings,
            analyzer_api=api,
            request_reason="引用链里缺转发原文",
        )
    )
    payload = json.loads(api.ai.calls[0][0][1]["content"])
    forward_item = next(
        item for item in payload["candidate_messages"] if item["id"] == "m-forward"
    )

    assert built.variant == "group_topic_expanded"
    assert built.topic_title == "硬盘选择"
    assert built.topic_confidence == 0.82
    assert built.topic_participants == ["转发者（提供转发）"]
    assert built.context_ids == ["m-current", "m-quote", "m-noise", "m-forward"]
    assert "合并转发摘要：" in built.recent_block
    assert "A：讨论了外接硬盘价格" in built.recent_block
    assert "B：提到 1TB 和 2TB 选择" in built.recent_block
    assert "A：讨论了外接硬盘价格" in forward_item["content"]


def test_expand_context_invalid_json_raises_topic_context_error():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "context": {"mode": "topic_ai"},
        }
    )
    source = _message("m-current", raw_message="现在聊什么")
    local_ctx = BuiltContext(
        context_ids=["m-current"],
        quoted_block="",
        recent_block="",
        current_block="[12:30] 20001: 现在聊什么",
        variant="group_topic_local",
        chat_type="group",
    )
    api = SimpleNamespace(ai=_FakeAIAPI("不是 JSON"))

    with pytest.raises(TopicContextError) as exc_info:
        asyncio.run(
            expand_context(
                source,
                local_ctx,
                _BridgeStub(None, [source]),
                settings,
                analyzer_api=api,
                request_reason="上下文不足",
            )
        )

    assert exc_info.value.analysis.error_code == "topic_invalid_tool_arguments"
