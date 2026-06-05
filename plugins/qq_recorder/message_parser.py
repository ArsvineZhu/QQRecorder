import html
import json
import re
from dataclasses import dataclass

from .sticker_detector import combined_detection


@dataclass
class ImageInfo:
    file_url: str
    file_unique: str
    file_size: int
    local_path: str = ""
    is_sticker: bool = False
    sticker_confidence: float = 0.0


@dataclass
class VideoInfo:
    file_url: str
    file_unique: str
    file_size: int
    duration_sec: int = 0
    title: str = ""
    intro: str = ""
    local_path: str = ""


@dataclass
class ReplyInfo:
    reply_to_message_id: str


@dataclass
class AtInfo:
    target_user_id: str


@dataclass
class AppShareInfo:
    """Parsed metadata from a QQ JSON/app share segment (Bilibili, NetEase, etc.)."""

    app_name: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    prompt: str = ""
    raw_data: str = ""


@dataclass
class ParsedMessage:
    text: str
    has_image: bool
    has_reply: bool
    has_forward: bool
    has_at: bool
    has_app_share: bool
    segments: list[dict]
    images: list[ImageInfo]
    videos: list[VideoInfo]
    replies: list[ReplyInfo]
    at_mentions: list[AtInfo]
    forward_ids: list[str]
    app_shares: list[AppShareInfo]


ALLOWED_SEGMENT_TYPES = {
    "text",
    "image",
    "video",
    "at",
    "reply",
    "forward",
    "face",
    "json",
}


def extract_text(segments: list[dict]) -> str:
    text_parts = []
    for seg in segments:
        if seg["type"] == "text":
            text_parts.append(seg["data"].get("text", ""))
    return "".join(text_parts)


def extract_images(segments: list[dict], raw_message: str = "") -> list[ImageInfo]:
    images = []
    for seg in segments:
        if seg["type"] == "image":
            data = seg["data"]
            file_url = data.get("url", "")
            file_unique = data.get("file_unique", "0")
            try:
                file_size = int(data.get("file_size", 0))
            except (ValueError, TypeError):
                file_size = 0

            is_sticker, sticker_confidence = combined_detection(
                raw_message=raw_message,
                segment_data=data,
            )

            images.append(
                ImageInfo(
                    file_url=file_url,
                    file_unique=file_unique,
                    file_size=file_size,
                    local_path=str(data.get("file") or data.get("path") or ""),
                    is_sticker=is_sticker,
                    sticker_confidence=sticker_confidence,
                )
            )
    return images


def extract_videos(segments: list[dict]) -> list[VideoInfo]:
    videos = []
    for seg in segments:
        if seg["type"] != "video":
            continue
        data = seg["data"]
        file_url = str(data.get("url", "") or "")
        file_unique = str(
            data.get("file_unique") or data.get("md5") or data.get("file_md5") or "0"
        )
        try:
            file_size = int(data.get("file_size") or data.get("size") or 0)
        except (ValueError, TypeError):
            file_size = 0
        try:
            duration_sec = int(
                data.get("duration") or data.get("seconds") or data.get("time") or 0
            )
        except (ValueError, TypeError):
            duration_sec = 0
        videos.append(
            VideoInfo(
                file_url=file_url,
                file_unique=file_unique,
                file_size=file_size,
                duration_sec=duration_sec,
                title=str(data.get("title", "") or ""),
                intro=str(data.get("desc", "") or ""),
                local_path=str(data.get("file") or data.get("path") or ""),
            )
        )
    return videos


def extract_replies(segments: list[dict]) -> list[ReplyInfo]:
    replies = []
    for seg in segments:
        if seg["type"] == "reply":
            reply_id = seg["data"].get("id", "")
            replies.append(ReplyInfo(reply_id))
    return replies


def extract_at_mentions(segments: list[dict]) -> list[AtInfo]:
    ats = []
    for seg in segments:
        if seg["type"] == "at":
            qq = str(seg["data"].get("qq", ""))
            ats.append(AtInfo(qq))
    return ats


_FORWARD_ID_RE = re.compile(r"\[CQ:forward,[^\]]*?\bid=([^,\]]+)")


def extract_forward_ids(segments: list[dict], raw_message: str = "") -> list[str]:
    forward_ids = []
    for seg in segments:
        if seg["type"] == "forward":
            forward_id = seg["data"].get("id", "").strip()
            if forward_id:
                forward_ids.append(forward_id)
    if not forward_ids and raw_message:
        for match in _FORWARD_ID_RE.finditer(raw_message):
            forward_id = match.group(1).strip()
            if forward_id:
                forward_ids.append(forward_id)
    return list(dict.fromkeys(forward_ids))


def extract_app_shares(segments: list[dict]) -> list[AppShareInfo]:
    """Extract metadata from QQ JSON/app share segments.

    Handles multiple QQ app share types:
    - com.tencent.structmsg (mini-program / 小程序)
    - com.tencent.tuwen.lua (rich media / 图文分享)
    - com.tencent.map (location share / 位置分享)
    - com.tencent.music (music / 音乐分享)
    """
    app_shares = []
    for seg in segments:
        if seg["type"] != "json":
            continue
        try:
            data = seg.get("data", {})
            data_str = data.get("data", "")
            if not data_str:
                continue
            # CQ code may HTML-encode special chars (&#44; = comma, etc.)
            decoded = html.unescape(data_str)
            obj = json.loads(decoded)

            # Extract app name: use desc, fall back to app package name
            app_name = obj.get("desc", "") or _extract_app_label(obj.get("app", ""))

            # Try multiple meta sub-keys for structured title/url
            meta = obj.get("meta", {})
            title = ""
            description = ""
            url = ""

            for key in ("detail_1", "news", "music", "Location.Search"):
                if key in meta:
                    detail = meta[key]
                    title = detail.get("title", "") or detail.get("name", "")
                    description = detail.get("desc", "")
                    url = (
                        detail.get("qqdocurl", "")
                        or detail.get("url", "")
                        or detail.get("jumpUrl", "")
                    )
                    if title or url:
                        break

            # Fallback: use prompt as title
            prompt = obj.get("prompt", "")
            if not title:
                title = prompt

            app_shares.append(
                AppShareInfo(
                    app_name=app_name,
                    title=title,
                    description=description,
                    url=url,
                    prompt=prompt,
                    raw_data=data_str,
                )
            )
        except (json.JSONDecodeError, TypeError, AttributeError):
            # Bare minimum: store raw data even if parsing fails
            app_shares.append(
                AppShareInfo(raw_data=seg.get("data", {}).get("data", ""))
            )
    return app_shares


def _extract_app_label(app_package: str) -> str:
    """Extract a human-readable label from an Android package name."""
    if not app_package:
        return ""
    # Known package names
    KNOWN = {
        "com.tencent.map": "QQ位置",
        "com.tencent.tuwen.lua": "QQ图文",
        "com.tencent.music": "QQ音乐",
        "com.tencent.structmsg": "QQ卡片",
    }
    for key, label in KNOWN.items():
        if key in app_package:
            return label
    return app_package.split(".")[-1] if "." in app_package else app_package


def build_segments_data(message_segments: list[dict]) -> list[dict]:
    segments = []
    for idx, seg in enumerate(message_segments):
        seg_type = seg["type"]
        if seg_type not in ALLOWED_SEGMENT_TYPES:
            continue
        segments.append(
            {
                "segment_type": seg_type,
                "segment_order": idx,
                "segment_data": json.dumps(seg["data"]),
            }
        )
    return segments


def parse_message(message_segments: list[dict], raw_message: str = "") -> ParsedMessage:
    text = extract_text(message_segments)
    images = extract_images(message_segments, raw_message)
    videos = extract_videos(message_segments)
    replies = extract_replies(message_segments)
    at_mentions = extract_at_mentions(message_segments)
    forward_ids = extract_forward_ids(message_segments, raw_message)
    app_shares = extract_app_shares(message_segments)
    segments = build_segments_data(message_segments)

    return ParsedMessage(
        text=text,
        has_image=len(images) > 0,
        has_reply=len(replies) > 0,
        has_forward=len(forward_ids) > 0,
        has_at=len(at_mentions) > 0,
        has_app_share=len(app_shares) > 0,
        segments=segments,
        images=images,
        videos=videos,
        replies=replies,
        at_mentions=at_mentions,
        forward_ids=forward_ids,
        app_shares=app_shares,
    )
