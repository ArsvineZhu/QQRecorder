"""Bridge between reply flow and the vision subsystem."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PIL import Image, ImageOps

from ..config import ReplyPluginSettings
from ..context.render import (
    display_name,
    first_reply_id,
    format_full_time,
    raw_message_text,
    render_line,
    render_message,
    strip_prefix,
)
from ..vision import (
    analyze_video,
    detect_image_intent,
    escalate_analysis,
    needs_escalation,
    render_video_context,
    render_visual_context,
    select_escalation_model,
    select_model,
)
from ..vision.analyzer import analyze_image as _analyze_image
from ..vision.cache import VisionCacheStore
from ..vision.quota import VisionQuotaTracker
from ..vision.schemas import VisualAnalysis

if TYPE_CHECKING:
    from openai import OpenAI


@dataclass(slots=True)
class PreparedImage:
    data: bytes
    mime_type: str


@dataclass(slots=True)
class VideoSource:
    url: str | None
    local_path: str | None
    file_size: int | None = None
    duration_sec: int | None = None
    title: str = ""
    intro: str = ""


class VisionBridge:
    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self.settings: ReplyPluginSettings = plugin.settings
        self.logger = plugin.logger

    @property
    def enabled(self) -> bool:
        vision = self.settings.vision
        return bool(
            vision.enabled
            and vision.include_in_context
            and self.plugin._vision_client is not None
            and self.plugin._vision_cache is not None
            and self.plugin._vision_quota is not None
        )

    async def build_context(self, source_msg, event) -> str:
        if not self.enabled:
            return ""

        light_ctx = await self._build_light_vision_context(source_msg, event)
        intent = detect_image_intent(self._get_user_text(event), self.settings)
        parts: list[str] = []

        images = getattr(source_msg, "images", []) or []
        if images:
            parts.extend(
                await self._analyze_images(source_msg, images, light_ctx, intent)
            )

        for video_source in self._extract_video_sources(event, source_msg):
            rendered = await self._analyze_video(source_msg, video_source, light_ctx)
            if rendered:
                parts.append(rendered)

        return "\n\n".join(parts)

    async def _analyze_images(  # noqa: C901
        self,
        source_msg,
        images,
        light_ctx: str,
        intent: str,
    ) -> list[str]:
        vision = self.settings.vision
        user_id = str(getattr(source_msg, "user_id", "") or "")
        chat_id = str(getattr(source_msg, "group_id", None) or source_msg.user_id)
        cache_version = self._cache_version()
        cache = self._require_cache()
        quota = self._require_quota()
        results: list[str] = []
        escalations_used = 0

        for index, image in enumerate(images):
            if index >= vision.max_images_per_message:
                break

            file_size = self._image_file_size(image)
            if (
                file_size is not None
                and file_size > vision.source_image_bytes_threshold
            ):
                self.logger.warning(
                    "vision: image too large (%d bytes), skipping", file_size
                )
                continue

            file_unique = str(getattr(image, "file_unique", "") or "")
            model = select_model(intent, file_size or 0, "", self.settings)

            cached = await cache.get_visual(
                file_unique,
                model,
                cache_version,
                ttl_days=vision.cache_ttl_days,
            )
            if cached is not None:
                results.append(render_visual_context(cached))
                continue

            if not quota.check_and_consume_image(user_id, chat_id):
                self.logger.warning(
                    "vision: image quota exhausted user=%s chat=%s", user_id, chat_id
                )
                continue

            if (
                file_unique
                and model != vision.image_fast_model
                and vision.cache_enabled
            ):
                cached_flash = await cache.get_visual(
                    file_unique,
                    vision.image_fast_model,
                    cache_version,
                    ttl_days=vision.cache_ttl_days,
                )
                if cached_flash is not None:
                    analysis = cached_flash
                    if (
                        escalations_used < vision.escalation_max_images_escalate
                        and needs_escalation(
                            cached_flash, intent, file_size or 0, self.settings
                        )
                    ):
                        escalated, escalated_model = await self._run_escalation(
                            cached_flash, image, intent, light_ctx
                        )
                        if escalated is not None and escalated_model is not None:
                            analysis = escalated
                            escalations_used += 1
                            await cache.put_visual(
                                file_unique,
                                escalated_model,
                                cache_version,
                                escalated,
                            )
                    if not analysis.error_code:
                        results.append(render_visual_context(analysis))
                    continue

            analysis = await self._analyze_single_image(
                image, file_unique, model, light_ctx
            )
            if analysis is None or analysis.error_code:
                continue

            if file_unique and vision.cache_enabled:
                await cache.put_visual(
                    file_unique,
                    model,
                    cache_version,
                    analysis,
                )

            if (
                escalations_used < vision.escalation_max_images_escalate
                and needs_escalation(analysis, intent, file_size or 0, self.settings)
            ):
                escalated, escalated_model = await self._run_escalation(
                    analysis, image, intent, light_ctx
                )
                if escalated is not None and escalated_model is not None:
                    analysis = escalated
                    escalations_used += 1
                    if file_unique and vision.cache_enabled:
                        await cache.put_visual(
                            file_unique,
                            escalated_model,
                            cache_version,
                            escalated,
                        )

            results.append(render_visual_context(analysis))

        return results

    async def _analyze_single_image(
        self,
        image,
        file_unique: str,
        model: str,
        light_ctx: str,
    ) -> VisualAnalysis | None:
        image_bytes = await self._get_image_bytes(image)
        if image_bytes is None:
            return None
        if len(image_bytes) > self.settings.vision.source_image_bytes_threshold:
            self.logger.warning(
                "vision: downloaded image too large (%d bytes), skipping",
                len(image_bytes),
            )
            return None

        prepared = _prepare_for_api(
            image_bytes,
            max_bytes=self.settings.vision.api_image_bytes_max,
        )
        image_b64 = base64.b64encode(prepared.data).decode("ascii")

        try:
            return await _analyze_image(
                self._require_client(),
                image_b64,
                file_unique,
                self.settings,
                chat_context=light_ctx,
                model_override=model,
                image_mime_type=prepared.mime_type,
            )
        except Exception as exc:
            self.logger.warning("vision: analyze_image failed: %s", exc)
            return None

    async def _run_escalation(
        self,
        initial: VisualAnalysis,
        image,
        intent: str,
        light_ctx: str,
    ) -> tuple[VisualAnalysis | None, str | None]:
        model = select_escalation_model(initial, intent, self.settings)
        if model is None:
            return None, None

        image_bytes = await self._get_image_bytes(image)
        if image_bytes is None:
            return None, model

        prepared = _prepare_for_api(
            image_bytes,
            max_bytes=self.settings.vision.api_image_bytes_max,
        )
        image_b64 = base64.b64encode(prepared.data).decode("ascii")

        try:
            analysis = await escalate_analysis(
                self._require_client(),
                image_b64,
                initial,
                intent,
                light_ctx,
                self.settings,
                model_override=model,
                image_mime_type=prepared.mime_type,
            )
        except Exception as exc:
            self.logger.warning("vision: escalation failed: %s", exc)
            return None, model

        if analysis.error_code:
            return None, model
        return analysis, model

    async def _analyze_video(
        self,
        source_msg,
        video_source: VideoSource,
        light_ctx: str,
    ) -> str | None:
        vision = self.settings.vision
        if (
            video_source.duration_sec is not None
            and video_source.duration_sec > vision.video_max_duration_min * 60
        ):
            self.logger.warning(
                "vision: video duration exceeds limit duration_sec=%s",
                video_source.duration_sec,
            )
            return None
        if (
            video_source.file_size is not None
            and video_source.file_size > vision.video_max_bytes
        ):
            self.logger.warning(
                "vision: video file too large file_size=%s", video_source.file_size
            )
            return None

        user_id = str(getattr(source_msg, "user_id", "") or "")
        chat_id = str(getattr(source_msg, "group_id", None) or source_msg.user_id)
        quota = self._require_quota()
        if not quota.check_and_consume_video(user_id, chat_id):
            self.logger.warning(
                "vision: video quota exhausted user=%s chat=%s", user_id, chat_id
            )
            return None

        source_key = video_source.local_path or video_source.url or ""
        if not source_key:
            return None

        cache_version = self._cache_version()
        file_unique = hashlib.md5(source_key.encode("utf-8")).hexdigest()
        cache = self._require_cache()
        cached = await cache.get_video(
            file_unique,
            vision.video_summary_model,
            cache_version,
            ttl_days=vision.cache_ttl_days,
        )
        if cached is not None:
            return render_video_context(cached)

        analysis = await analyze_video(
            self._require_client(),
            video_file_path=video_source.local_path,
            video_url=video_source.url,
            file_unique=file_unique,
            settings=self.settings,
            chat_context=light_ctx,
            title=video_source.title,
            intro=video_source.intro,
        )
        if analysis.error_code:
            self.logger.warning(
                "vision: video analysis returned error file=%s error=%s",
                source_key,
                analysis.error_code,
            )
            return None

        if vision.cache_enabled:
            await cache.put_video(
                file_unique,
                vision.video_summary_model,
                cache_version,
                analysis,
            )
        return render_video_context(analysis)

    async def _build_light_vision_context(self, source_msg, event) -> str:
        parts = [f"发送者：{display_name(source_msg)}"]
        timestamp = getattr(source_msg, "timestamp", None)
        if timestamp:
            parts.append(f"时间：{format_full_time(timestamp)}")

        current_text = self._get_user_text(event)
        if current_text:
            parts.append(f"当前消息：{current_text}")

        reply_to_id = first_reply_id(source_msg)
        if reply_to_id and self.plugin._bridge is not None:
            quoted = await self.plugin._bridge.get_message(reply_to_id)
            if quoted is not None:
                quoted_text = render_message(quoted, settings=self.settings)
                if quoted_text:
                    parts.append(f"引用消息：{quoted_text}")

        recent_block = await self._build_recent_context_block(source_msg, reply_to_id)
        if recent_block:
            parts.append(f"最近消息：\n{recent_block}")

        return "\n".join(parts)

    async def _build_recent_context_block(
        self,
        source_msg,
        reply_to_id: str | None,
    ) -> str:
        bridge = self.plugin._bridge
        if bridge is None:
            return ""

        chat_type = str(getattr(source_msg, "chat_type", "") or "")
        chat_id = str(
            getattr(source_msg, "group_id", None)
            or getattr(source_msg, "user_id", "")
            or ""
        )
        timestamp = getattr(source_msg, "timestamp", None)
        if not chat_type or not chat_id or timestamp is None:
            return ""

        if chat_type == "group":
            limit = min(6, self.settings.context.local_recent_limit_group)
            window = min(
                20, self.settings.context.local_recent_time_window_minutes_group
            )
        else:
            limit = min(6, self.settings.context.local_recent_limit_private)
            window = min(
                20, self.settings.context.local_recent_time_window_minutes_private
            )

        recent_messages = await bridge.get_recent_window(
            chat_type,
            chat_id,
            limit=limit + 2,
            since_minutes=window,
            before_or_at=timestamp,
        )
        current_id = str(getattr(source_msg, "message_id", "") or "")
        lines: list[str] = []
        for message in reversed(recent_messages):
            message_id = str(getattr(message, "message_id", "") or "")
            if message_id in {current_id, reply_to_id or ""}:
                continue
            rendered = render_line(
                message,
                sender_name=display_name(message),
                settings=self.settings,
            )
            if rendered:
                lines.append(rendered)
            if len(lines) >= limit:
                break
        return "\n".join(lines)

    async def _get_image_bytes(self, image) -> bytes | None:
        local_path = str(getattr(image, "local_path", "") or "").strip()
        if local_path and os.path.isfile(local_path):
            try:
                return await asyncio.to_thread(Path(local_path).read_bytes)
            except OSError as exc:
                self.logger.warning(
                    "vision: failed to read local image %s: %s", local_path, exc
                )

        file_url = str(getattr(image, "file_url", "") or "").strip()
        if file_url:
            try:
                from ..compat import import_sibling_plugin_module

                download_image = import_sibling_plugin_module(
                    "qq_recorder.image_handler"
                ).download_image
                data, _ = await download_image(file_url, timeout=30)
                return data
            except Exception as exc:
                self.logger.warning(
                    "vision: failed to download image %s: %s", file_url, exc
                )

        self.logger.warning("vision: no local_path or file_url for image")
        return None

    def _extract_video_sources(self, event, source_msg) -> list[VideoSource]:
        results: list[VideoSource] = []
        seen: set[tuple[str | None, str | None]] = set()
        for segment in self._iter_segments(event, source_msg):
            if str(segment.get("type", "") or "") != "video":
                continue
            data = segment.get("data", {}) or {}
            url = _clean_string(data.get("url"))
            local_path = _clean_string(data.get("file")) or _clean_string(
                data.get("path")
            )
            if local_path and local_path.startswith("http"):
                url, local_path = local_path, None
            key = (url, local_path)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                VideoSource(
                    url=url,
                    local_path=local_path,
                    file_size=_maybe_int(
                        data.get("file_size")
                        or data.get("size")
                        or data.get("filesize")
                    ),
                    duration_sec=_maybe_int(
                        data.get("duration") or data.get("seconds") or data.get("time")
                    ),
                    title=_clean_string(data.get("title")) or "",
                    intro=_clean_string(data.get("desc")) or "",
                )
            )

        if results:
            return results

        raw = str(
            getattr(event, "raw_message", "") or raw_message_text(source_msg) or ""
        )
        match = re.search(r"\[CQ:video,[^\]]*?url=([^,\]]+)", raw)
        if not match:
            return []
        return [VideoSource(url=match.group(1).strip(), local_path=None)]

    def _iter_segments(self, event, source_msg) -> list[dict[str, Any]]:
        event_segments = getattr(event, "message", None) or []
        if event_segments:
            result: list[dict[str, Any]] = []
            for segment in event_segments:
                if hasattr(segment, "to_dict"):
                    result.append(cast(dict[str, Any], segment.to_dict()))
                elif isinstance(segment, dict):
                    result.append(cast(dict[str, Any], segment))
            if result:
                return result

        message_segments = getattr(source_msg, "segments", []) or []
        result: list[dict[str, Any]] = []
        for segment in message_segments:
            if getattr(segment, "segment_type", "") != "video":
                continue
            try:
                data = json.loads(str(getattr(segment, "segment_data", "") or "{}"))
            except json.JSONDecodeError:
                data = {}
            result.append({"type": getattr(segment, "segment_type", ""), "data": data})
        return result

    def _get_user_text(self, event) -> str:
        raw = str(getattr(event, "raw_message", "") or "")
        text = re.sub(r"\[CQ:[^\]]+\]", "", raw).strip()
        return strip_prefix(text, self.settings.trigger.prefixes)

    def _cache_version(self) -> str:
        vision = self.settings.vision
        return f"{vision.prompt_version}:{vision.schema_version}"

    def _require_client(self) -> OpenAI:
        client = self.plugin._vision_client
        assert client is not None
        return client

    def _require_cache(self) -> VisionCacheStore:
        cache = self.plugin._vision_cache
        assert cache is not None
        return cache

    def _require_quota(self) -> VisionQuotaTracker:
        quota = self.plugin._vision_quota
        assert quota is not None
        return quota

    @staticmethod
    def _image_file_size(image) -> int | None:
        file_size = _maybe_int(getattr(image, "file_size", None))
        if file_size is not None and file_size > 0:
            return file_size
        local_path = str(getattr(image, "local_path", "") or "").strip()
        if local_path and os.path.isfile(local_path):
            try:
                return os.path.getsize(local_path)
            except OSError:
                return None
        return None


def _prepare_for_api(image_bytes: bytes, *, max_bytes: int) -> PreparedImage:
    original_mime = _guess_image_mime(image_bytes)
    if len(image_bytes) <= max_bytes:
        return PreparedImage(image_bytes, original_mime)

    image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes)))
    if getattr(image, "is_animated", False):
        image.seek(0)

    if _has_alpha(image):
        prepared = _compress_png(image, max_bytes)
        if prepared is not None:
            return prepared

    prepared = _compress_jpeg(_flatten_to_rgb(image), max_bytes)
    if prepared is not None:
        return prepared

    fallback = _compress_jpeg(_flatten_to_rgb(image), max_bytes, min_side=16)
    if fallback is not None:
        return fallback
    return PreparedImage(image_bytes, original_mime)


def _compress_png(image: Image.Image, max_bytes: int) -> PreparedImage | None:
    best: bytes | None = None
    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2):
        resized = _resize_image(image, scale)
        candidate = _save_image(resized, "PNG", optimize=True, compress_level=9)
        if best is None or len(candidate) < len(best):
            best = candidate
        if len(candidate) <= max_bytes:
            return PreparedImage(candidate, "image/png")
    if best is not None and len(best) <= max_bytes:
        return PreparedImage(best, "image/png")
    return None


def _compress_jpeg(
    image: Image.Image,
    max_bytes: int,
    *,
    min_side: int = 64,
) -> PreparedImage | None:
    best: bytes | None = None
    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2):
        resized = _resize_image(image, scale, min_side=min_side)
        for quality in (85, 75, 65, 55, 45, 35, 25):
            candidate = _save_image(
                resized,
                "JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            if best is None or len(candidate) < len(best):
                best = candidate
            if len(candidate) <= max_bytes:
                return PreparedImage(candidate, "image/jpeg")
    if best is not None and len(best) <= max_bytes:
        return PreparedImage(best, "image/jpeg")
    return None


def _resize_image(
    image: Image.Image,
    scale: float,
    *,
    min_side: int = 64,
) -> Image.Image:
    if scale >= 0.999:
        return image.copy()
    width = max(min_side, int(image.width * scale))
    height = max(min_side, int(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _save_image(image: Image.Image, fmt: str, **kwargs) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGB", "L"):
        return image.convert("RGB")
    canvas = Image.new("RGB", image.size, (255, 255, 255))
    alpha = image.getchannel("A") if "A" in image.getbands() else None
    canvas.paste(image.convert("RGBA"), mask=alpha)
    return canvas


def _has_alpha(image: Image.Image) -> bool:
    return "A" in image.getbands() or image.mode in {"RGBA", "LA", "PA"}


def _guess_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _maybe_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_string(value) -> str | None:
    text = str(value or "").strip()
    return text or None
