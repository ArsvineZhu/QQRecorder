import asyncio
import json
from types import SimpleNamespace

from plugins.grok.tools import media_tools
from plugins.grok.vision.schemas import normalize_analysis
from plugins.grok.vision.video_schemas import VideoAnalysis


class _CacheStub:
    async def get_visual(self, *args, **kwargs):
        return None

    async def get_video(self, *args, **kwargs):
        return None

    async def put_visual(self, *args, **kwargs):
        return None

    async def put_video(self, *args, **kwargs):
        return None


class _QuotaStub:
    def __init__(self, *, allow_image=True, allow_video=True):
        self.allow_image = allow_image
        self.allow_video = allow_video
        self.image_calls = []
        self.video_calls = []

    def check_and_consume_image(self, user_id, chat_id):
        self.image_calls.append((user_id, chat_id))
        return self.allow_image

    def check_and_consume_video(self, user_id, chat_id):
        self.video_calls.append((user_id, chat_id))
        return self.allow_video


def _settings(*, cache_enabled=False):
    return SimpleNamespace(
        vision=SimpleNamespace(
            api_image_bytes_max=1024 * 1024,
            image_fast_model="image-model",
            video_summary_model="video-model",
            cache_ttl_days=30,
            cache_enabled=cache_enabled,
            prompt_version="prompt-v1",
            schema_version="schema-v1",
        )
    )


def _media_tool(plugin, name):
    return next(
        tool for tool in media_tools.build_media_tools(plugin) if tool.name == name
    )


def test_read_picture_checks_quota_before_paid_model(tmp_path, monkeypatch):
    async def _run():
        image_path = tmp_path / "image.bin"
        image_path.write_bytes(b"not-really-an-image")
        quota = _QuotaStub(allow_image=False)
        plugin = SimpleNamespace(
            _vision_client=object(),
            _vision_cache=_CacheStub(),
            _vision_quota=quota,
            _bridge=None,
            settings=_settings(),
        )
        message = SimpleNamespace(
            id=10,
            user_id="20001",
            group_id="30001",
            raw_message="图片消息",
            images=[
                SimpleNamespace(id=1, local_path=str(image_path), file_unique="fu")
            ],
        )

        async def _fail_analyze_image(*args, **kwargs):
            raise AssertionError("paid image model should not be called")

        monkeypatch.setattr(media_tools, "analyze_image", _fail_analyze_image)

        result = await _media_tool(plugin, "read_picture").handler(
            {"source_msg": message, "user_id": "20001", "chat_id": "30001"},
            {},
        )

        assert result.status == "failed"
        assert result.error_code == "vision_quota_exceeded"
        assert result.retryable is False
        assert result.data == {"media_type": "image"}
        assert quota.image_calls == [("20001", "30001")]

    asyncio.run(_run())


def test_read_video_resolves_message_id_before_extracting_sources(monkeypatch):
    async def _run():
        old_message = SimpleNamespace(
            id=20,
            message_id="old-video",
            user_id="20002",
            group_id="30001",
            raw_message="旧视频消息",
            segments=[
                SimpleNamespace(
                    segment_type="video",
                    segment_data=json.dumps(
                        {
                            "url": "https://example.test/old.mp4",
                            "file": "/tmp/old.mp4",
                            "title": "old title",
                            "desc": "old intro",
                        }
                    ),
                )
            ],
        )
        current_message = SimpleNamespace(
            id=21,
            message_id="current",
            user_id="20001",
            group_id="30001",
            raw_message="当前消息",
            segments=[],
        )
        event = SimpleNamespace(
            message=[
                {
                    "type": "video",
                    "data": {
                        "url": "https://example.test/current.mp4",
                        "file": "/tmp/current.mp4",
                        "title": "current title",
                    },
                }
            ]
        )
        plugin = SimpleNamespace(
            _vision_client=object(),
            _vision_cache=_CacheStub(),
            _vision_quota=None,
            _bridge=SimpleNamespace(get_message=lambda message_id: old_message),
            settings=_settings(),
        )
        captured = {}

        async def _get_message(message_id):
            captured["message_id"] = message_id
            return old_message

        plugin._bridge.get_message = _get_message

        async def _analyze_video(
            client,
            local_path,
            url,
            file_unique,
            settings,
            *,
            chat_context,
            title,
            intro,
        ):
            del client, file_unique, settings
            captured.update(
                {
                    "local_path": local_path,
                    "url": url,
                    "chat_context": chat_context,
                    "title": title,
                    "intro": intro,
                }
            )
            return VideoAnalysis(video_type="clip", confidence=0.9)

        async def _persist_analysis(*args, **kwargs):
            captured["message_db_id"] = kwargs["message_db_id"]

        monkeypatch.setattr(media_tools, "analyze_video", _analyze_video)
        monkeypatch.setattr(media_tools, "_persist_analysis", _persist_analysis)

        result = await _media_tool(plugin, "read_video").handler(
            {"source_msg": current_message, "event": event},
            {"message_id": "old-video"},
        )

        assert result.status == "ok"
        assert captured["message_id"] == "old-video"
        assert captured["local_path"] == "/tmp/old.mp4"
        assert captured["url"] == "https://example.test/old.mp4"
        assert captured["chat_context"] == "旧视频消息"
        assert captured["title"] == "old title"
        assert captured["intro"] == "old intro"
        assert captured["message_db_id"] == 20

    asyncio.run(_run())


def test_read_video_checks_quota_before_paid_model(monkeypatch):
    async def _run():
        quota = _QuotaStub(allow_video=False)
        plugin = SimpleNamespace(
            _vision_client=object(),
            _vision_cache=_CacheStub(),
            _vision_quota=quota,
            _bridge=None,
            settings=_settings(),
        )
        message = SimpleNamespace(
            id=20,
            user_id="20002",
            group_id="30001",
            raw_message="视频消息",
            segments=[
                SimpleNamespace(
                    segment_type="video",
                    segment_data=json.dumps(
                        {"url": "https://example.test/video.mp4", "file": "/tmp/v.mp4"}
                    ),
                )
            ],
        )

        async def _fail_analyze_video(*args, **kwargs):
            raise AssertionError("paid video model should not be called")

        monkeypatch.setattr(media_tools, "analyze_video", _fail_analyze_video)

        result = await _media_tool(plugin, "read_video").handler(
            {"source_msg": message, "user_id": "20002", "chat_id": "30001"},
            {},
        )

        assert result.status == "failed"
        assert result.error_code == "vision_quota_exceeded"
        assert result.retryable is False
        assert result.data == {"media_type": "video"}
        assert quota.video_calls == [("20002", "30001")]

    asyncio.run(_run())


def test_read_picture_persists_semantic_text(tmp_path, monkeypatch):
    async def _run():
        image_path = tmp_path / "image.bin"
        image_path.write_bytes(b"not-really-an-image")
        plugin = SimpleNamespace(
            _vision_client=object(),
            _vision_cache=_CacheStub(),
            _vision_quota=None,
            _bridge=None,
            settings=_settings(),
        )
        message = SimpleNamespace(
            id=10,
            user_id="20001",
            group_id="30001",
            raw_message="图片消息",
            images=[
                SimpleNamespace(id=1, local_path=str(image_path), file_unique="fu")
            ],
        )
        captured = {}

        async def _analyze_image(*args, **kwargs):
            del args, kwargs
            return normalize_analysis(
                {
                    "image_type": "meme",
                    "literal_content": {"summary": "图里有一段文字"},
                    "semantic_interpretation": {"main_meaning": "在吐槽加班"},
                    "confidence": 0.8,
                }
            )

        async def _persist_analysis(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(media_tools, "analyze_image", _analyze_image)
        monkeypatch.setattr(media_tools, "_persist_analysis", _persist_analysis)

        result = await _media_tool(plugin, "read_picture").handler(
            {"source_msg": message, "user_id": "20001", "chat_id": "30001"},
            {},
        )

        assert result.status == "ok"
        assert "图片类型：meme" in captured["semantic_text"]
        assert "画面概述：图里有一段文字" in captured["semantic_text"]
        assert "核心含义：在吐槽加班" in captured["semantic_text"]

    asyncio.run(_run())


def test_read_video_persists_semantic_text(monkeypatch):
    async def _run():
        plugin = SimpleNamespace(
            _vision_client=object(),
            _vision_cache=_CacheStub(),
            _vision_quota=None,
            _bridge=None,
            settings=_settings(),
        )
        message = SimpleNamespace(
            id=20,
            user_id="20002",
            group_id="30001",
            raw_message="视频消息",
            segments=[
                SimpleNamespace(
                    segment_type="video",
                    segment_data=json.dumps(
                        {"url": "https://example.test/video.mp4", "file": "/tmp/v.mp4"}
                    ),
                )
            ],
        )
        captured = {}

        async def _analyze_video(*args, **kwargs):
            del args, kwargs
            return VideoAnalysis(
                video_type="screen_recording",
                duration_summary="约 24 秒",
                visual_summary="录屏展示聊天窗口",
                semantic_meaning="在说明沟通混乱",
                confidence=0.7,
            )

        async def _persist_analysis(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(media_tools, "analyze_video", _analyze_video)
        monkeypatch.setattr(media_tools, "_persist_analysis", _persist_analysis)

        result = await _media_tool(plugin, "read_video").handler(
            {"source_msg": message, "user_id": "20002", "chat_id": "30001"},
            {},
        )

        assert result.status == "ok"
        assert "视频类型：screen_recording" in captured["semantic_text"]
        assert "时长：约 24 秒" in captured["semantic_text"]
        assert "核心含义：在说明沟通混乱" in captured["semantic_text"]

    asyncio.run(_run())
