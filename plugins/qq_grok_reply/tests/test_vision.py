import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from PIL import Image

from plugins.qq_grok_reply.app.vision_bridge import VisionBridge, _prepare_for_api
from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.context import BuiltContext
from plugins.qq_grok_reply.vision.cache import VisionCacheRow, VisionCacheStore
from plugins.qq_grok_reply.vision.schemas import (
    AffectiveReading,
    ContextDependency,
    LiteralContent,
    SemanticInterpretation,
    ToneItem,
    Uncertainty,
    VisualAnalysis,
    render_visual_context,
)
from plugins.qq_grok_reply.vision.video_schemas import (
    KeyEvent,
    VideoAffectiveReading,
    VideoAnalysis,
    VideoUncertainty,
    render_video_context,
)


def _message(
    message_id: str,
    text: str,
    *,
    sender: str = "User",
    timestamp: datetime | None = None,
):
    return SimpleNamespace(
        id=1,
        message_id=message_id,
        chat_type="group",
        group_id="30001",
        user_id="20001",
        timestamp=timestamp or datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        raw_message=text,
        images=[],
        replies=[],
        app_shares=[],
        forward_messages=[],
        at_mentions=[],
        sender_nickname=sender,
        sender_card="",
        segments=[
            SimpleNamespace(
                segment_type="text",
                segment_order=0,
                segment_data=json.dumps({"text": text}, ensure_ascii=False),
            )
        ],
    )


def test_vision_cache_round_trip_for_visual_and_video(tmp_path):
    async def _run() -> None:
        db_path = tmp_path / "vision-cache.sqlite3"
        store = VisionCacheStore(str(db_path))
        await store.init_db()

        visual = VisualAnalysis(image_type="meme", confidence=0.8)
        video = VideoAnalysis(video_type="screen_recording", confidence=0.7)

        await store.put_visual("img-1", "flash", "v1:s1", visual)
        await store.put_video("vid-1", "video", "v1:s1", video)

        cached_visual = await store.get_visual("img-1", "flash", "v1:s1")
        cached_video = await store.get_video("vid-1", "video", "v1:s1")

        assert cached_visual is not None
        assert cached_visual.image_type == "meme"
        assert cached_video is not None
        assert cached_video.video_type == "screen_recording"

        await store.close()

    asyncio.run(_run())


def test_vision_cache_ttl_expires_old_entries(tmp_path):
    async def _run() -> None:
        db_path = tmp_path / "vision-cache-expire.sqlite3"
        store = VisionCacheStore(str(db_path))
        await store.init_db()
        await store.put_visual(
            "img-2", "flash", "v1:s1", VisualAnalysis(image_type="real_photo")
        )

        session_factory = store._Session
        assert session_factory is not None

        def _age_entry() -> None:
            with session_factory() as session:  # type: ignore[operator]
                row = (
                    session.query(VisionCacheRow).filter_by(file_unique="img-2").first()
                )
                assert row is not None
                row.created_at = datetime.now(UTC) - timedelta(days=3)
                session.commit()

        await asyncio.to_thread(_age_entry)

        expired = await store.get_visual("img-2", "flash", "v1:s1", ttl_days=1)
        assert expired is None

        await store.close()

    asyncio.run(_run())


def test_prepare_for_api_returns_valid_resized_image():
    image = Image.effect_noise((1024, 1024), 120).convert("RGB")
    original_buffer = _save_png(image)
    prepared = _prepare_for_api(original_buffer, max_bytes=50_000)

    assert len(prepared.data) <= 50_000
    assert prepared.mime_type in {"image/png", "image/jpeg"}
    assert prepared.data.startswith((b"\x89PNG", b"\xff\xd8\xff"))


def test_light_vision_context_includes_quote_and_recent_messages():
    async def _run() -> None:
        settings = build_config(
            {
                "enabled": True,
                "recorder_db": "C:/tmp/recorder.db",
                "vision": {"enabled": True, "dashscope_api_key": "key"},
            }
        )
        quoted = _message("quoted-1", "这是引用", sender="Quoted")
        recent_a = _message(
            "recent-1",
            "第一条最近消息",
            sender="A",
            timestamp=datetime(2026, 6, 3, 11, 58, tzinfo=UTC),
        )
        recent_b = _message(
            "recent-2",
            "第二条最近消息",
            sender="B",
            timestamp=datetime(2026, 6, 3, 11, 59, tzinfo=UTC),
        )
        source = _message(
            "source-1",
            "[CQ:image,file=1]",
            sender="Sender",
            timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        )
        source.replies = [SimpleNamespace(reply_to_message_id="quoted-1")]

        class _Bridge:
            async def get_message(self, message_id: str):
                return quoted if message_id == "quoted-1" else None

            async def get_recent_window(self, *_args, **_kwargs):
                return [recent_b, recent_a, source]

        plugin = SimpleNamespace(
            settings=settings,
            logger=SimpleNamespace(
                info=lambda *args, **kwargs: None,
                warning=lambda *args, **kwargs: None,
            ),
            _vision_client=object(),
            _vision_cache=object(),
            _vision_quota=object(),
            _bridge=_Bridge(),
        )
        bridge = VisionBridge(plugin)
        event = SimpleNamespace(raw_message="/ask 看看这个图")

        context = await bridge._build_light_vision_context(source, event)

        assert "当前消息：看看这个图" in context
        assert "引用消息：这是引用" in context
        assert "A: 第一条最近消息" in context
        assert "B: 第二条最近消息" in context

    asyncio.run(_run())


def test_extract_video_sources_from_event_segments():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "vision": {"enabled": True, "dashscope_api_key": "key"},
        }
    )
    plugin = SimpleNamespace(
        settings=settings,
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None
        ),
        _vision_client=object(),
        _vision_cache=object(),
        _vision_quota=object(),
        _bridge=None,
    )
    bridge = VisionBridge(plugin)
    event = SimpleNamespace(
        raw_message="[CQ:video,url=https://example.com/demo.mp4]",
        message=[
            {
                "type": "video",
                "data": {
                    "url": "https://example.com/demo.mp4",
                    "file_size": "2048",
                    "duration": "31",
                    "title": "demo",
                },
            }
        ],
    )

    videos = bridge._extract_video_sources(event, _message("source-2", "video"))

    assert len(videos) == 1
    assert videos[0].url == "https://example.com/demo.mp4"
    assert videos[0].file_size == 2048
    assert videos[0].duration_sec == 31
    assert videos[0].title == "demo"


def test_enrich_context_adds_visual_results_for_quoted_and_recent_images(monkeypatch):
    async def _run() -> None:
        settings = build_config(
            {
                "enabled": True,
                "recorder_db": "C:/tmp/recorder.db",
                "vision": {"enabled": True, "dashscope_api_key": "key"},
            }
        )
        source = _message(
            "source-1",
            "这里说什么了",
            sender="Sender",
            timestamp=datetime(2026, 6, 3, 12, 1, tzinfo=UTC),
        )
        source.replies = [SimpleNamespace(reply_to_message_id="quoted-1")]
        quoted = _message(
            "quoted-1",
            "",
            sender="Quoted",
            timestamp=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
        )
        quoted.has_image = True
        quoted.segments = [
            SimpleNamespace(
                segment_type="image",
                segment_order=0,
                segment_data=json.dumps({"url": "https://example.com/quoted.png"}),
            )
        ]
        quoted.images = [SimpleNamespace(file_unique="quoted-image")]
        recent = _message(
            "recent-1",
            "",
            sender="Recent",
            timestamp=datetime(2026, 6, 3, 11, 59, tzinfo=UTC),
        )
        recent.has_image = True
        recent.segments = [
            SimpleNamespace(
                segment_type="image",
                segment_order=0,
                segment_data=json.dumps({"url": "https://example.com/recent.png"}),
            )
        ]
        recent.images = [SimpleNamespace(file_unique="recent-image")]

        class _Bridge:
            async def get_message(self, message_id: str):
                mapping = {
                    "quoted-1": quoted,
                    "recent-1": recent,
                }
                return mapping.get(message_id)

            async def get_recent_window(self, *_args, **_kwargs):
                return [recent, source]

        plugin = SimpleNamespace(
            settings=settings,
            logger=SimpleNamespace(
                info=lambda *args, **kwargs: None,
                warning=lambda *args, **kwargs: None,
            ),
            _vision_client=object(),
            _vision_cache=object(),
            _vision_quota=object(),
            _bridge=_Bridge(),
        )
        bridge = VisionBridge(plugin)
        event = SimpleNamespace(raw_message="[CQ:reply,id=quoted-1]这里说什么了")
        built = BuiltContext(
            context_ids=["source-1", "quoted-1", "recent-1"],
            quoted_block="[12:00] Quoted: [图片: 已下载]",
            recent_block="[11:59] Recent: [图片: 已下载]",
            current_block="[12:01] Sender: 这里说什么了",
            variant="private_topic_local",
            chat_type="private",
        )

        async def _fake_analyze_images(message, images, light_ctx: str, intent: str):
            assert "当前消息：这里说什么了" in light_ctx
            assert intent == "default"
            return [f"analysis:{message.message_id}:{len(images)}"]

        monkeypatch.setattr(bridge, "_analyze_images", _fake_analyze_images)

        enriched = await bridge.enrich_context(source, event, built)

        assert "关联消息ID：quoted-1" in enriched.visual_context
        assert "关联消息：[12:00] Quoted: [图片]" in enriched.visual_context
        assert "analysis:quoted-1:1" in enriched.visual_context
        assert "关联消息ID：recent-1" in enriched.visual_context
        assert "关联消息：[11:59] Recent: [图片]" in enriched.visual_context
        assert "analysis:recent-1:1" in enriched.visual_context

    asyncio.run(_run())


def test_render_visual_context_exposes_richer_fields_with_budget():
    analysis = VisualAnalysis(
        image_type="meme",
        literal_content=LiteralContent(
            summary="一个人举着手机，对着聊天截图露出无语表情",
            visible_objects=["手机", "聊天截图", "人物表情"],
            visible_people=["年轻男性"],
            scene="室内桌边自拍",
            ocr_text=["你又在改需求", "今晚发版"],
        ),
        semantic_interpretation=SemanticInterpretation(
            main_meaning="在吐槽需求反复变动",
            implied_message="说话人觉得这次改动很折腾",
            meme_or_cultural_reference="常见打工人吐槽梗图",
            text_image_relation="截图里的文字解释了人物表情为何无语",
        ),
        confidence=0.86,
        affective_reading=AffectiveReading(
            tone=[
                ToneItem(label="阴阳怪气", intensity=0.9),
                ToneItem(label="无奈", intensity=0.7),
            ],
            evidence="皱眉表情和截图文字共同强化了抱怨语气",
        ),
        context_dependency=ContextDependency(
            requires_context=True,
            used_context="用户在追问这张图是什么意思",
            meaning_without_context="单看是在吐槽工作聊天",
            meaning_with_context="结合群聊内容，更像是在影射当前讨论",
        ),
        uncertainty=Uncertainty(
            ambiguous_points=["人物是否真在自拍无法完全确认"],
            possible_alternative_meanings=["也可能只是单纯展示聊天记录"],
        ),
    )

    rendered = render_visual_context(analysis)

    assert "图片类型：meme" in rendered
    assert "可见对象：" in rendered
    assert "图文关系：" in rendered
    assert "结合上下文：" in rendered
    assert "歧义点：" in rendered
    assert len(rendered) <= 1200


def test_render_video_context_exposes_events_and_audio_with_budget():
    analysis = VideoAnalysis(
        video_type="screen_recording",
        duration_summary="约 24 秒",
        visual_summary="录屏展示聊天窗口不断弹出新消息",
        key_events=[
            KeyEvent(time_range="00:01-00:05", event="打开群聊并停留在争论截图"),
            KeyEvent(time_range="00:06-00:12", event="快速滚动查看前文"),
        ],
        visible_text=["你先别改", "我已经提交了"],
        audio_or_speech_summary="背景有人说先别上线，语气比较急",
        semantic_meaning="视频在说明一次临近发版时的沟通混乱",
        contextual_meaning="结合当前提问，更像是在让机器人判断谁在背锅",
        affective_reading=VideoAffectiveReading(
            tone=[
                ToneItem(label="着急", intensity=0.8),
                ToneItem(label="埋怨", intensity=0.6),
            ],
            evidence="语速快且停留在争执内容上",
        ),
        uncertainty=VideoUncertainty(
            ambiguous_points=["无法确认说话者具体身份"],
            possible_alternative_meanings=["也可能只是普通工作同步"],
        ),
        confidence=0.74,
    )

    rendered = render_video_context(analysis)

    assert "视频类型：screen_recording" in rendered
    assert "关键事件：" in rendered
    assert "音频/语音：" in rendered
    assert "结合上下文：" in rendered
    assert "备选解释：" in rendered
    assert len(rendered) <= 1200


def _save_png(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
