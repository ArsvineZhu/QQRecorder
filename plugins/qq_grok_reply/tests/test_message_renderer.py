import json
from types import SimpleNamespace

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context.message_renderer import render_message_text


def _segment(segment_type: str, data: dict, order: int):
    return SimpleNamespace(
        segment_type=segment_type,
        segment_data=json.dumps(data, ensure_ascii=False),
        segment_order=order,
    )


def _message(**kwargs):
    defaults = {
        "raw_message": "",
        "segments": [],
        "images": [],
        "replies": [],
        "forward_messages": [],
        "at_mentions": [],
        "app_shares": [],
        "has_image": False,
        "has_reply": False,
        "has_forward": False,
        "has_at": False,
        "has_app_share": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_render_message_text_rebuilds_segments_in_order():
    settings = build_config({"enabled": True, "recorder_db": "C:/tmp/recorder.db"})
    message = _message(
        raw_message="你好",
        has_image=True,
        has_reply=True,
        has_at=True,
        segments=[
            _segment("text", {"text": "你好"}, 0),
            _segment("at", {"qq": "10001"}, 1),
            _segment("reply", {"id": "msg-1"}, 2),
            _segment(
                "image",
                {"url": "https://example.com/a.png", "file_size": 2048},
                3,
            ),
            _segment("face", {"id": "14", "text": "[微笑]"}, 4),
        ],
        images=[
            SimpleNamespace(
                file_size=2048,
                width=320,
                height=240,
                downloaded=True,
                is_sticker=False,
                file_url="https://example.com/a.png",
            )
        ],
        replies=[SimpleNamespace(reply_to_message_id="msg-1")],
    )

    rendered = render_message_text(message, settings=settings)

    assert rendered == (
        "你好 @10001 [回复: msg-1] [图片: 320x240, 2048B, 已下载] [表情: [微笑]]"
    )


def test_render_message_text_renders_forward_share_and_payload_fallback():
    settings = build_config({"enabled": True, "recorder_db": "C:/tmp/recorder.db"})
    long_raw_data = (
        '{"desc":"QQ卡片","meta":{"news":{"title":"硬盘推荐"}},'
        '"extra":"abcdefghijklmnopqrstuvwxyz"}'
    )
    message = _message(
        raw_message="看这个",
        has_forward=True,
        has_app_share=True,
        segments=[
            _segment("text", {"text": "看这个"}, 0),
            _segment("forward", {"id": "fw-1"}, 1),
            _segment("json", {"data": long_raw_data}, 2),
            _segment("mystery", {"foo": "bar"}, 3),
        ],
        forward_messages=[
            SimpleNamespace(
                id=1, depth=0, nickname="A", user_id="20001", content_summary="先看 1TB"
            ),
            SimpleNamespace(
                id=2, depth=1, nickname="B", user_id="20002", content_summary="再看 2TB"
            ),
        ],
        app_shares=[
            SimpleNamespace(
                app_name="B站",
                title="硬盘推荐",
                description="2TB 选购",
                url="https://example.com/share",
                prompt="推荐一下",
                raw_data=long_raw_data,
            )
        ],
    )

    rendered = render_message_text(message, settings=settings)

    assert "看这个" in rendered
    assert "合并转发摘要：" in rendered
    assert "A：先看 1TB" in rendered
    assert "B：再看 2TB" in rendered
    assert (
        "B站 | 硬盘推荐 | 2TB 选购 | https://example.com/share | 推荐一下" in rendered
    )
    assert '[mystery: {"foo": "bar"}]' in rendered


def test_render_message_text_uses_raw_payload_when_share_metadata_is_missing():
    settings = build_config({"enabled": True, "recorder_db": "C:/tmp/recorder.db"})
    raw_data = '{"foo":"bar","long":"0123456789abcdefghijklmnopqrstuvwxyz"}'
    message = _message(
        has_app_share=True,
        segments=[_segment("json", {"data": raw_data}, 0)],
        app_shares=[
            SimpleNamespace(
                app_name="",
                title="",
                description="",
                url="",
                prompt="",
                raw_data=raw_data,
            )
        ],
    )

    rendered = render_message_text(message, settings=settings)

    assert rendered.startswith("[分享原始数据:")
    assert "0123456789" in rendered
    assert len(rendered) < len(raw_data) + 20
