import json
from typing import Any

from ..compat import import_sibling_plugin_module
from ..config import ReplyPluginSettings

unescape_text = import_sibling_plugin_module("qq_recorder.text_utils").unescape_text

RAW_PAYLOAD_PREVIEW = 120


def render_message_text(message, *, settings: ReplyPluginSettings) -> str:
    rendered_parts: list[str] = []
    fallback_parts: list[str] = []

    for segment in _ordered_segments(message):
        primary, fallback = _render_segment(segment, message=message, settings=settings)
        if primary:
            rendered_parts.append(primary)
        if fallback:
            fallback_parts.append(fallback)

    structured_text = _join_parts(rendered_parts).strip()
    fallback_text = _join_parts(fallback_parts).strip()
    if structured_text and fallback_text:
        return f"{structured_text} {fallback_text}"
    if structured_text:
        return structured_text
    if fallback_text:
        return fallback_text

    raw = _visible_raw_text(getattr(message, "raw_message", "") or "")
    if raw:
        return raw
    return _fallback_from_features(message)


def render_forward_tree(message, *, settings: ReplyPluginSettings) -> str:
    lines = ["合并转发摘要："]
    used = len(lines[0])
    truncated = False
    for item in _ordered_forwards(getattr(message, "forward_messages", []) or []):
        line = _render_forward_line(item)
        if not line:
            continue
        next_used = used + len(line) + 1
        if len(lines) > settings.context.forward_max_items or (
            next_used > settings.context.forward_max_chars
        ):
            truncated = True
            break
        lines.append(line)
        used = next_used
    if len(lines) == 1:
        return ""
    if truncated:
        lines.append("……已截断")
    return "\n".join(lines)


def _ordered_segments(message) -> list[Any]:
    segments = list(getattr(message, "segments", []) or [])
    return sorted(
        segments,
        key=lambda item: (
            getattr(item, "segment_order", 0),
            getattr(item, "id", 0),
        ),
    )


def _ordered_forwards(forwards: list[Any]) -> list[Any]:
    return sorted(
        forwards,
        key=lambda item: (
            getattr(item, "depth", 0),
            getattr(item, "id", 0),
        ),
    )


def _render_segment(
    segment, *, message, settings: ReplyPluginSettings
) -> tuple[str, str]:
    segment_type = str(getattr(segment, "segment_type", "") or "")
    data = _load_segment_data(getattr(segment, "segment_data", "") or "")

    if segment_type == "text":
        return _safe_text(data.get("text", "")), ""
    if segment_type == "at":
        target = str(data.get("qq", "") or data.get("target_user_id", "") or "").strip()
        return (f"@{target}" if target else "[提及]"), ""
    if segment_type == "reply":
        reply_id = str(data.get("id", "") or "").strip()
        return (f"[回复: {reply_id}]" if reply_id else "[回复]"), ""
    if segment_type == "forward":
        summary = render_forward_tree(message, settings=settings)
        return (summary if summary else "[合并转发]"), ""
    if segment_type == "json":
        return _render_app_share(message, data)
    if segment_type == "image":
        return _render_image(message, data), ""
    if segment_type == "face":
        return _render_face(data), ""

    fallback = _payload_preview(data)
    return "", (f"[{segment_type or '未知段'}: {fallback}]" if fallback else "[未知段]")


def _render_app_share(message, data: dict[str, Any]) -> tuple[str, str]:
    share = (getattr(message, "app_shares", []) or [None])[0]
    if share is not None:
        parts = [
            str(getattr(share, "app_name", "") or "").strip(),
            str(getattr(share, "title", "") or "").strip(),
            str(getattr(share, "description", "") or "").strip(),
            str(getattr(share, "url", "") or "").strip(),
            str(getattr(share, "prompt", "") or "").strip(),
        ]
        normalized = " | ".join(part for part in parts if part)
        raw_data = str(getattr(share, "raw_data", "") or "").strip()
        if normalized:
            fallback = _preview_text(raw_data) if raw_data else ""
            return normalized, (f"[原始分享数据: {fallback}]" if fallback else "")
        fallback = _preview_text(raw_data)
        return (f"[分享原始数据: {fallback}]" if fallback else "[分享]"), ""

    raw_data = str(data.get("data", "") or "").strip()
    fallback = _preview_text(raw_data)
    return (f"[分享原始数据: {fallback}]" if fallback else "[分享]"), ""


def _render_image(message, data: dict[str, Any]) -> str:
    images = list(getattr(message, "images", []) or [])
    image = images[0] if images else None
    is_sticker = bool(
        (image is not None and getattr(image, "is_sticker", False))
        or str(data.get("subType", "") or data.get("sub_type", "")) in {"1", "7", "13"}
    )
    parts = ["[表情" if is_sticker else "[图片"]

    width = _coerce_int(
        data.get("width")
        if data.get("width") is not None
        else getattr(image, "width", None)
    )
    height = _coerce_int(
        data.get("height")
        if data.get("height") is not None
        else getattr(image, "height", None)
    )
    details: list[str] = []
    if width and height:
        details.append(f"{width}x{height}")

    size = _coerce_int(
        data.get("file_size")
        if data.get("file_size") is not None
        else getattr(image, "file_size", None)
    )
    if size:
        details.append(f"{size}B")

    downloaded = getattr(image, "downloaded", False) if image is not None else False
    if downloaded:
        details.append("已下载")

    url = str(data.get("url", "") or getattr(image, "file_url", "") or "").strip()
    if not url and (data.get("file") or data.get("file_id")):
        details.append("含引用")

    if details:
        parts[0] += f": {', '.join(details)}]"
    else:
        parts[0] += "]"
    return parts[0]


def _render_face(data: dict[str, Any]) -> str:
    name = str(data.get("text", "") or data.get("name", "") or "").strip()
    face_id = str(data.get("id", "") or data.get("face_id", "") or "").strip()
    if name:
        return f"[表情: {name}]"
    if face_id:
        return f"[表情#{face_id}]"
    return "[表情]"


def _render_forward_line(item) -> str:
    nickname = str(
        getattr(item, "nickname", "") or getattr(item, "user_id", "") or "未知"
    )
    summary = _safe_text(getattr(item, "content_summary", "") or "")
    if not summary:
        return ""
    return f"{nickname}：{summary}"


def _load_segment_data(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return data if isinstance(data, dict) else {"raw": raw}


def _visible_raw_text(raw_message: str) -> str:
    raw = _safe_text(raw_message)
    if not raw:
        return ""
    lines = [line.strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def _safe_text(value: Any) -> str:
    return unescape_text(str(value or "")).strip()


def _fallback_from_features(message) -> str:
    if getattr(message, "has_forward", False):
        return "[合并转发]"
    if getattr(message, "has_app_share", False):
        return "[分享]"
    if getattr(message, "has_reply", False):
        return "[回复]"
    if getattr(message, "has_image", False):
        return "[图片]"
    return ""


def _payload_preview(data: dict[str, Any]) -> str:
    if not data:
        return ""
    try:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    except TypeError:
        raw = str(data)
    return _preview_text(raw)


def _preview_text(text: str) -> str:
    clean = _safe_text(text)
    if len(clean) <= RAW_PAYLOAD_PREVIEW:
        return clean
    return clean[: RAW_PAYLOAD_PREVIEW - 1] + "…"


def _join_parts(parts: list[str]) -> str:
    joined: list[str] = []
    for part in parts:
        value = str(part or "").strip()
        if value:
            joined.append(value)
    return " ".join(joined)


def _coerce_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
