from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import aiohttp

from ..infra import get_analysis, save_analysis
from ..shared import load_schema
from ..vision.analyzer import analyze_image
from ..vision.image_prep import prepare_for_api
from ..vision.schemas import analysis_to_dict, render_visual_context
from ..vision.video_analyzer import analyze_video
from ..vision.video_schemas import render_video_context, video_analysis_to_dict
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
        if plugin._vision_client is None:
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
        model_used = plugin.settings.vision.image_fast_model

        cached = await get_analysis(plugin._bridge, file_unique, model_used=model_used)
        if cached:
            payload = json.loads(cached)
            msg_text = str(getattr(message, "raw_message", "") or "")
            payload["message_text"] = msg_text[:600]
            _log_cache_event(
                plugin,
                media_type="image",
                file_unique=file_unique,
                model_used=model_used,
                cache_hit=True,
                semantic_text=payload.get("semantic_text", ""),
            )
            return ToolResponse(status="ok", data=payload)

        quota = getattr(plugin, "_vision_quota", None)
        user_id: str | None = None
        chat_id: str | None = None
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
        if analysis.error_code and quota is not None and user_id is not None:
            quota.rollback_image(user_id, chat_id or "unknown_chat")
        payload = analysis_to_dict(analysis)
        semantic_text = render_visual_context(analysis)
        await _persist_analysis(
            plugin,
            file_unique=file_unique,
            analysis=analysis,
            payload=payload,
            media_type="image",
            image_id=getattr(image, "id", None),
            semantic_text=semantic_text,
            message_db_id=getattr(message, "id", None),
        )
        _log_cache_event(
            plugin,
            media_type="image",
            file_unique=file_unique,
            model_used=model_used,
            cache_hit=False,
            semantic_text=semantic_text,
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
        if plugin._vision_client is None:
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
        model_used = plugin.settings.vision.video_summary_model

        cached = await get_analysis(plugin._bridge, file_unique, model_used=model_used)
        if cached:
            payload = json.loads(cached)
            _log_cache_event(
                plugin,
                media_type="video",
                file_unique=file_unique,
                model_used=model_used,
                cache_hit=True,
                semantic_text=payload.get("semantic_text", ""),
            )
            return ToolResponse(status="ok", data=payload)

        quota = getattr(plugin, "_vision_quota", None)
        user_id: str | None = None
        chat_id: str | None = None
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
        if analysis.error_code and quota is not None and user_id is not None:
            quota.rollback_video(user_id, chat_id or "unknown_chat")
        payload = video_analysis_to_dict(analysis)
        semantic_text = render_video_context(analysis)
        await _persist_analysis(
            plugin,
            file_unique=file_unique,
            analysis=analysis,
            payload=payload,
            media_type="video",
            image_id=None,
            semantic_text=semantic_text,
            video_id=video.get("id"),
            message_db_id=getattr(message, "id", None),
        )
        _log_cache_event(
            plugin,
            media_type="video",
            file_unique=file_unique,
            model_used=model_used,
            cache_hit=False,
            semantic_text=semantic_text,
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


def _extract_video_from_stored(video) -> dict[str, Any]:
    return {
        "id": getattr(video, "id", None),
        "url": _clean_string(getattr(video, "file_url", None)),
        "local_path": _clean_string(getattr(video, "local_path", None)),
        "title": _clean_string(getattr(video, "title", None)) or "",
        "intro": _clean_string(getattr(video, "intro", None)) or "",
    }


def _extract_video_from_event_segment(segment) -> dict[str, Any] | None:
    if hasattr(segment, "to_dict"):
        segment = segment.to_dict()
    if not isinstance(segment, dict) or str(segment.get("type", "")) != "video":
        return None
    data = segment.get("data", {}) or {}
    return {
        "id": None,
        "url": _clean_string(data.get("url")),
        "local_path": _clean_string(data.get("file"))
        or _clean_string(data.get("path")),
        "title": _clean_string(data.get("title")) or "",
        "intro": _clean_string(data.get("desc")) or "",
    }


def _extract_video_from_source_segment(segment) -> dict[str, Any] | None:
    if getattr(segment, "segment_type", "") != "video":
        return None
    try:
        data = json.loads(str(getattr(segment, "segment_data", "") or "{}"))
    except json.JSONDecodeError:
        data = {}
    return {
        "id": None,
        "url": _clean_string(data.get("url")),
        "local_path": _clean_string(data.get("file"))
        or _clean_string(data.get("path")),
        "title": _clean_string(data.get("title")) or "",
        "intro": _clean_string(data.get("desc")) or "",
    }


def _extract_video_sources(event, source_msg) -> list[dict[str, Any]]:
    """Collect video sources in priority order."""
    stored_videos = getattr(source_msg, "videos", []) or []
    if stored_videos:
        result = [_extract_video_from_stored(v) for v in stored_videos]
        if result:
            return result

    result: list[dict[str, Any]] = []
    for segment in getattr(event, "message", None) or []:
        extracted = _extract_video_from_event_segment(segment)
        if extracted is not None:
            result.append(extracted)
    if result:
        return result

    for segment in getattr(source_msg, "segments", []) or []:
        extracted = _extract_video_from_source_segment(segment)
        if extracted is not None:
            result.append(extracted)
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


async def _persist_analysis(
    plugin,
    *,
    file_unique,
    analysis,
    payload,
    media_type,
    image_id,
    video_id=None,
    semantic_text,
    message_db_id,
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
        semantic_text=semantic_text,
        confidence=analysis.confidence,
        prompt_version=vision.prompt_version,
        schema_version=vision.schema_version,
        image_id=image_id,
        video_id=video_id,
        message_db_id=message_db_id,
    )
    _log_persist_event(
        plugin,
        media_type=media_type,
        file_unique=file_unique,
        model_used=(
            vision.image_fast_model
            if media_type == "image"
            else vision.video_summary_model
        ),
        semantic_text=semantic_text,
    )


def _log_cache_event(
    plugin,
    *,
    media_type: str,
    file_unique: str,
    model_used: str,
    cache_hit: bool,
    semantic_text: str,
) -> None:
    logger = getattr(plugin, "logger", None)
    if logger is None or not hasattr(logger, "info"):
        return
    logger.info(
        "vision read_%s file_unique=%s model=%s cache_hit=%s semantic_text_chars=%d",
        media_type,
        file_unique,
        model_used,
        cache_hit,
        len(str(semantic_text or "")),
    )


def _log_persist_event(
    plugin,
    *,
    media_type: str,
    file_unique: str,
    model_used: str,
    semantic_text: str,
) -> None:
    logger = getattr(plugin, "logger", None)
    if logger is None or not hasattr(logger, "info"):
        return
    logger.info(
        (
            "vision save_%s file_unique=%s model=%s"
            " analysis_saved=true semantic_text_chars=%d"
        ),
        media_type,
        file_unique,
        model_used,
        len(str(semantic_text or "")),
    )
