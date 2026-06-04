from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import aiohttp

from ..infra import save_analysis
from ..shared import load_schema
from ..vision.analyzer import analyze_image
from ..vision.cache import VisionCacheStore
from ..vision.image_prep import prepare_for_api
from ..vision.schemas import analysis_to_dict
from ..vision.video_analyzer import analyze_video
from ..vision.video_schemas import video_analysis_to_dict
from .registry import ToolDefinition, ToolResponse


def build_media_tools(plugin) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="read_picture",
            description="Analyze an image attached to a recorded message.",
            schema=load_schema("tools/read_picture.json"),
            handler=_read_picture_handler(plugin),
        ),
        ToolDefinition(
            name="read_video",
            description=(
                "Analyze a video attached to the current event or recorded message."
            ),
            schema=load_schema("tools/read_video.json"),
            handler=_read_video_handler(plugin),
        ),
    ]


def _read_picture_handler(plugin):
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        if plugin._vision_client is None or plugin._vision_cache is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="vision_unavailable",
                message="vision client not configured",
            )
        message = await _resolve_message(plugin, context, arguments)
        if message is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="message_not_found",
                message="message not available",
            )
        images = getattr(message, "images", []) or []
        if not images:
            return ToolResponse(
                status="failed",
                data={},
                error_code="image_not_found",
                message="message has no image",
            )
        image = images[0]
        image_bytes = await _read_image_bytes(image)
        if image_bytes is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="image_unavailable",
                message="image bytes unavailable",
            )
        prepared = prepare_for_api(
            image_bytes,
            max_bytes=plugin.settings.vision.api_image_bytes_max,
        )
        file_unique = (
            str(getattr(image, "file_unique", "") or "")
            or hashlib.md5(image_bytes).hexdigest()
        )
        cache_version = _cache_version(plugin)
        cache: VisionCacheStore = plugin._vision_cache
        cached = await cache.get_visual(
            file_unique,
            plugin.settings.vision.image_fast_model,
            cache_version,
            ttl_days=plugin.settings.vision.cache_ttl_days,
        )
        if cached is not None:
            return ToolResponse(status="ok", data=analysis_to_dict(cached))

        quota = getattr(plugin, "_vision_quota", None)
        if quota is not None:
            user_id, chat_id = _quota_identity(context, message)
            if not quota.check_and_consume_image(user_id, chat_id):
                return _quota_failed("image")

        b64 = base64.b64encode(prepared.data).decode("ascii")
        analysis = await analyze_image(
            plugin._vision_client,
            b64,
            file_unique,
            plugin.settings,
            chat_context=str(getattr(message, "raw_message", "") or ""),
            image_mime_type=prepared.mime_type,
        )
        if plugin.settings.vision.cache_enabled:
            await cache.put_visual(
                file_unique,
                plugin.settings.vision.image_fast_model,
                cache_version,
                analysis,
            )
        payload = analysis_to_dict(analysis)
        await _persist_analysis(
            plugin,
            file_unique=file_unique,
            analysis=analysis,
            payload=payload,
            media_type="image",
            image_id=getattr(image, "id", None),
            message_db_id=getattr(message, "id", None),
        )
        # Attach the message text alongside image analysis
        msg_text = str(getattr(message, "raw_message", "") or "")
        payload["message_text"] = msg_text[:600]
        return ToolResponse(
            status="ok" if not analysis.error_code else "failed",
            data=payload,
            error_code=analysis.error_code or None,
        )

    return _handler


def _read_video_handler(plugin):
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        if plugin._vision_client is None or plugin._vision_cache is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="vision_unavailable",
                message="vision client not configured",
            )
        message = await _resolve_message(plugin, context, arguments)
        if message is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="message_not_found",
                message="message not available",
                retryable=False,
            )
        source_msg = context.get("source_msg")
        event = context.get("event") if message is source_msg else None
        videos = _extract_video_sources(event, message)
        if not videos:
            return ToolResponse(
                status="failed",
                data={},
                error_code="video_not_found",
                message="no video source available",
            )
        video = videos[0]
        file_unique = hashlib.sha1(
            f"{video['url']}|{video['local_path']}".encode()
        ).hexdigest()
        cache_version = _cache_version(plugin)
        cache: VisionCacheStore = plugin._vision_cache
        cached = await cache.get_video(
            file_unique,
            plugin.settings.vision.video_summary_model,
            cache_version,
            ttl_days=plugin.settings.vision.cache_ttl_days,
        )
        if cached is not None:
            return ToolResponse(status="ok", data=video_analysis_to_dict(cached))

        quota = getattr(plugin, "_vision_quota", None)
        if quota is not None:
            user_id, chat_id = _quota_identity(context, message)
            if not quota.check_and_consume_video(user_id, chat_id):
                return _quota_failed("video")

        analysis = await analyze_video(
            plugin._vision_client,
            video["local_path"],
            video["url"],
            file_unique,
            plugin.settings,
            chat_context=str(getattr(message, "raw_message", "") or ""),
            title=video["title"],
            intro=video["intro"],
        )
        if plugin.settings.vision.cache_enabled:
            await cache.put_video(
                file_unique,
                plugin.settings.vision.video_summary_model,
                cache_version,
                analysis,
            )
        payload = video_analysis_to_dict(analysis)
        await _persist_analysis(
            plugin,
            file_unique=file_unique,
            analysis=analysis,
            payload=payload,
            media_type="video",
            image_id=None,
            message_db_id=getattr(message, "id", None),
        )
        return ToolResponse(
            status="ok" if not analysis.error_code else "failed",
            data=payload,
            error_code=analysis.error_code or None,
        )

    return _handler


async def _resolve_message(plugin, context: dict[str, Any], arguments: dict[str, Any]):
    message_id = str(arguments.get("message_id") or "")
    source_msg = context.get("source_msg")

    # Force fresh reload for "current" or empty message_id
    # (source_msg may be stale — local_path may have been updated by async download)
    if not message_id or message_id.lower() in ("current", "now"):
        if plugin._bridge is not None and source_msg is not None:
            sid = str(getattr(source_msg, "message_id", "") or "")
            if sid:
                fresh = await plugin._bridge.get_message(sid)
                if fresh is not None:
                    return fresh
        return source_msg

    if plugin._bridge is None:
        return None
    return await plugin._bridge.get_message(message_id)


async def _read_image_bytes(image) -> bytes | None:
    local_path = str(getattr(image, "local_path", "") or "")
    if local_path and Path(local_path).exists():
        return await asyncio.to_thread(Path(local_path).read_bytes)

    file_url = str(getattr(image, "file_url", "") or "")
    if not file_url:
        return None
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(file_url) as response:
            if response.status >= 400:
                return None
            return await response.read()


def _extract_video_sources(event, source_msg) -> list[dict[str, Any]]:
    segments = getattr(event, "message", None) or []
    result: list[dict[str, Any]] = []
    if segments:
        for segment in segments:
            if hasattr(segment, "to_dict"):
                segment = segment.to_dict()
            if not isinstance(segment, dict) or str(segment.get("type", "")) != "video":
                continue
            data = segment.get("data", {}) or {}
            result.append(
                {
                    "url": _clean_string(data.get("url")),
                    "local_path": _clean_string(data.get("file"))
                    or _clean_string(data.get("path")),
                    "title": _clean_string(data.get("title")) or "",
                    "intro": _clean_string(data.get("desc")) or "",
                }
            )
    if result:
        return result

    source_segments = getattr(source_msg, "segments", []) or []
    for segment in source_segments:
        if getattr(segment, "segment_type", "") != "video":
            continue
        try:
            data = json.loads(str(getattr(segment, "segment_data", "") or "{}"))
        except json.JSONDecodeError:
            data = {}
        result.append(
            {
                "url": _clean_string(data.get("url")),
                "local_path": _clean_string(data.get("file"))
                or _clean_string(data.get("path")),
                "title": _clean_string(data.get("title")) or "",
                "intro": _clean_string(data.get("desc")) or "",
            }
        )
    return result


def _quota_identity(context: dict[str, Any], message: Any) -> tuple[str, str]:
    user_id = str(
        context.get("user_id") or getattr(message, "user_id", "") or "unknown_user"
    )
    chat_id = str(
        context.get("chat_id")
        or getattr(message, "group_id", "")
        or getattr(message, "user_id", "")
        or "unknown_chat"
    )
    return user_id, chat_id


def _quota_failed(media_type: str) -> ToolResponse:
    label = "图片" if media_type == "image" else "视频"
    return ToolResponse(
        status="failed",
        data={"media_type": media_type},
        error_code="vision_quota_exceeded",
        message=f"今日{label}视觉分析额度已用尽",
        retryable=False,
    )


def _clean_string(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _cache_version(plugin) -> str:
    vision = plugin.settings.vision
    return f"{vision.prompt_version}:{vision.schema_version}"


async def _persist_analysis(
    plugin, *, file_unique, analysis, payload, media_type, image_id, message_db_id
):
    """Write analysis result to recorder's permanent image_analyses table."""
    vision = plugin.settings.vision
    await save_analysis(
        plugin._bridge,
        file_unique=file_unique,
        model_used=(
            vision.image_fast_model
            if media_type == "image"
            else vision.video_summary_model
        ),
        analysis_json=json.dumps(payload, ensure_ascii=False),
        media_type=media_type,
        image_type=payload.get("image_type", "") or payload.get("media_type", ""),
        confidence=analysis.confidence,
        prompt_version=vision.prompt_version,
        schema_version=vision.schema_version,
        image_id=image_id,
        message_db_id=message_db_id,
    )
