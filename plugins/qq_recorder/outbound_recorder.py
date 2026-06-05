from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .message_parser import parse_message
from .text_utils import escape_text


def install_outbound_recording(api, storage, *, bot_uin: str, logger) -> None:
    qq_client = getattr(api, "qq", None)
    raw_api = getattr(qq_client, "_api", None)
    if qq_client is None or raw_api is None:
        return
    if getattr(raw_api, "_qqrecorder_outbound_wrapped", False):
        return

    original_group = raw_api.send_group_msg
    original_private = raw_api.send_private_msg
    original_forward = raw_api.send_forward_msg

    async def _send_group_msg(group_id, message, **kwargs):
        result = await original_group(group_id, message, **kwargs)
        await _record_outbound_message(
            storage,
            bot_uin=bot_uin,
            chat_type="group",
            chat_id=str(group_id),
            result=result,
            message=message,
            logger=logger,
        )
        return result

    async def _send_private_msg(user_id, message, **kwargs):
        result = await original_private(user_id, message, **kwargs)
        await _record_outbound_message(
            storage,
            bot_uin=bot_uin,
            chat_type="private",
            chat_id=str(user_id),
            result=result,
            message=message,
            logger=logger,
        )
        return result

    async def _send_forward_msg(message_type, target_id, messages, **kwargs):
        result = await original_forward(message_type, target_id, messages, **kwargs)
        await _record_outbound_message(
            storage,
            bot_uin=bot_uin,
            chat_type=str(message_type),
            chat_id=str(target_id),
            result=result,
            message=[],
            logger=logger,
            forward_payload=messages,
        )
        return result

    raw_api.send_group_msg = _send_group_msg
    raw_api.send_private_msg = _send_private_msg
    raw_api.send_forward_msg = _send_forward_msg
    raw_api._qqrecorder_outbound_wrapped = True


async def _record_outbound_message(
    storage,
    *,
    bot_uin: str,
    chat_type: str,
    chat_id: str,
    result,
    message: list[dict[str, Any]],
    logger,
    forward_payload: list[dict[str, Any]] | None = None,
) -> None:
    message_id = str(getattr(result, "message_id", "") or "").strip()
    if not message_id:
        return

    try:
        message_data = _build_outbound_message_data(
            message_id=message_id,
            bot_uin=bot_uin,
            chat_type=chat_type,
            chat_id=chat_id,
            message=message,
            forward_payload=forward_payload,
        )
        await storage.save_message(message_data)
    except Exception as exc:
        logger.warning("Failed to record outbound message %s: %s", message_id, exc)


def _build_outbound_message_data(
    *,
    message_id: str,
    bot_uin: str,
    chat_type: str,
    chat_id: str,
    message: list[dict[str, Any]],
    forward_payload: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if forward_payload is not None:
        raw_message = "[CQ:forward]"
        return {
            "message_id": message_id,
            "user_id": bot_uin,
            "sender_nickname": bot_uin,
            "sender_card": "",
            "group_id": chat_id if chat_type == "group" else None,
            "chat_type": chat_type,
            "timestamp": datetime.now(),
            "raw_message": escape_text(raw_message),
            "segments": [
                {
                    "segment_type": "forward",
                    "segment_order": 0,
                    "segment_data": json.dumps(
                        {"messages": forward_payload},
                        ensure_ascii=False,
                    ),
                }
            ],
            "images": [],
            "videos": [],
            "replies": [],
            "forward_messages": [],
            "at_mentions": [],
            "app_shares": [],
        }

    raw_message = _segments_to_raw_message(message)
    parsed = parse_message(message, raw_message)
    return {
        "message_id": message_id,
        "user_id": bot_uin,
        "sender_nickname": bot_uin,
        "sender_card": "",
        "group_id": chat_id if chat_type == "group" else None,
        "chat_type": chat_type,
        "timestamp": datetime.now(),
        "raw_message": escape_text(raw_message),
        "segments": parsed.segments,
        "images": [
            {
                "file_url": img.file_url,
                "file_unique": img.file_unique,
                "file_size": img.file_size,
                "local_path": img.local_path or None,
                "downloaded": bool(img.local_path and os.path.exists(img.local_path)),
                "is_sticker": img.is_sticker,
                "sticker_confidence": img.sticker_confidence,
            }
            for img in parsed.images
        ],
        "videos": [
            {
                "file_url": video.file_url,
                "file_unique": video.file_unique,
                "file_size": video.file_size,
                "local_path": video.local_path or None,
                "duration_sec": video.duration_sec,
                "downloaded": bool(
                    video.local_path and os.path.exists(video.local_path)
                ),
                "title": video.title,
                "intro": video.intro,
            }
            for video in parsed.videos
        ],
        "replies": [
            {"reply_to_message_id": reply.reply_to_message_id}
            for reply in parsed.replies
        ],
        "forward_messages": [],
        "at_mentions": [
            {"target_user_id": at.target_user_id} for at in parsed.at_mentions
        ],
        "app_shares": [
            {
                "app_name": share.app_name,
                "title": share.title,
                "description": share.description,
                "url": share.url,
                "prompt": share.prompt,
                "raw_data": share.raw_data,
            }
            for share in parsed.app_shares
        ],
    }


def _render_cq_text(data: dict) -> str:
    return str(data.get("text", "") or "")


def _render_cq_reply(data: dict) -> str:
    reply_id = str(data.get("id", "") or "").strip()
    return f"[CQ:reply,id={reply_id}]"


def _render_cq_at(data: dict) -> str:
    target = str(data.get("qq", "") or data.get("target_user_id", "") or "")
    return f"[CQ:at,qq={target}]"


def _render_cq_image(data: dict) -> str:
    return (
        f"[CQ:image,file={data.get('file', '') or ''},url={data.get('url', '') or ''}]"
    )


def _render_cq_video(data: dict) -> str:
    return (
        f"[CQ:video,file={data.get('file', '') or ''},url={data.get('url', '') or ''}]"
    )


def _render_cq_forward(data: dict) -> str:
    return "[CQ:forward]"


def _render_cq_json(data: dict) -> str:
    return str(data.get("data", "") or "")


def _render_cq_face(data: dict) -> str:
    return f"[CQ:face,id={data.get('id', '') or ''}]"


_SEGMENT_RENDERERS: dict[str, Callable[[dict], str]] = {
    "text": _render_cq_text,
    "reply": _render_cq_reply,
    "at": _render_cq_at,
    "image": _render_cq_image,
    "video": _render_cq_video,
    "forward": _render_cq_forward,
    "json": _render_cq_json,
    "face": _render_cq_face,
}


def _segments_to_raw_message(message: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type", "") or "")
        data = segment.get("data", {}) or {}
        renderer = _SEGMENT_RENDERERS.get(segment_type)
        if renderer:
            parts.append(renderer(data))
        else:
            parts.append(f"[CQ:{segment_type}]")
    return "".join(parts)
