from __future__ import annotations

import logging
from typing import Any

from ..compat import import_sibling_plugin_module
from ..shared import load_schema
from .registry import ToolDefinition, ToolResponse

_text_utils = import_sibling_plugin_module("qq_recorder.text_utils")
_forward_parser = import_sibling_plugin_module("qq_recorder.forward_parser")
unescape_text = _text_utils.unescape_text
flatten_forward_nodes = _forward_parser.flatten_forward_nodes
parse_forward_response = _forward_parser.parse_forward_response

logger = logging.getLogger("grok.context_tools")


def build_context_tools(plugin) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="track_reply",
            description=(
                "Trace the explicit reply chain for a message inside the current chat."
            ),
            schema=load_schema("tools/track_reply.json"),
            handler=_track_reply_handler(plugin),
        ),
        ToolDefinition(
            name="load_context",
            description="Load recent messages for the current chat scope.",
            schema=load_schema("tools/load_context.json"),
            handler=_load_context_handler(plugin),
        ),
        ToolDefinition(
            name="load_message",
            description="Load one recorded message by its message_id.",
            schema=load_schema("tools/load_message.json"),
            handler=_load_message_handler(plugin),
        ),
        ToolDefinition(
            name="extract_forward",
            description="Extract flattened forward content from a recorded message.",
            schema=load_schema("tools/extract_forward.json"),
            handler=_extract_forward_handler(plugin),
        ),
    ]


def _track_reply_handler(plugin):
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        bridge = plugin._bridge
        source_msg = await _resolve_message(plugin, context, arguments)
        if bridge is None or source_msg is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="message_not_found",
                message="source message not available",
            )
        max_depth = int(arguments.get("max_depth", 6) or 3)
        chain = await bridge.get_reply_chain(source_msg, max_depth=max_depth)
        data = {
            "messages": [await _message_payload(bridge, item) for item in chain],
            "root_message_id": str(chain[-1].message_id) if chain else None,
        }
        if not chain:
            return ToolResponse(
                status="failed",
                data=data,
                error_code="reply_chain_not_found",
                message=(
                    "这条引用链已经查询完，记录中没有可用结果，不要再次调用 track_reply"
                ),
                retryable=False,
            )
        return ToolResponse(status="ok", data=data)

    return _handler


def _load_context_handler(plugin):
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        bridge = plugin._bridge
        source_msg = context.get("source_msg")
        if bridge is None or source_msg is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="message_not_found",
                message="source message not available",
            )
        chat_type = str(
            getattr(source_msg, "chat_type", "") or context.get("chat_type")
        )
        chat_id = str(
            getattr(source_msg, "group_id", None)
            or getattr(source_msg, "user_id", "")
            or context.get("chat_id", "")
        )
        anchor = await _resolve_anchor_message(plugin, context, arguments)
        if anchor is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="anchor_message_not_found",
                message="anchor message not available",
            )
        direction = str(arguments.get("direction", "backward") or "backward")
        limit = int(arguments.get("limit", 12) or 12)
        since_minutes_raw = arguments.get("since_minutes")
        since_minutes = (
            int(since_minutes_raw or 30) if since_minutes_raw is not None else None
        )
        before = int(arguments.get("before", limit) or limit)
        after = int(arguments.get("after", 0) or 0)
        include_forward_preview = bool(arguments.get("include_forward_preview", False))
        include_vision_preview = bool(arguments.get("include_vision_preview", False))

        if direction == "around":
            items = await bridge.get_neighbors(
                chat_type,
                chat_id,
                anchor=anchor,
                before_limit=before,
                after_limit=after,
            )
        elif direction == "forward":
            items = await bridge.get_after(
                anchor,
                limit=limit,
                since_minutes=since_minutes,
            )
        else:
            items = await bridge.get_recent_window(
                chat_type,
                chat_id,
                limit=limit,
                since_minutes=int(since_minutes or 30),
                before_or_at=getattr(anchor, "timestamp", None),
            )
        payload_messages = [
            await _message_payload(
                bridge,
                item,
                include_forward_preview=include_forward_preview,
                include_vision_preview=include_vision_preview,
            )
            for item in items
        ]
        return ToolResponse(
            status="ok",
            data={
                "anchor_message_id": str(getattr(anchor, "message_id", "") or ""),
                "messages": payload_messages,
                "prev_cursor": None,
                "next_cursor": None,
                "range": {
                    "direction": direction,
                    "before": before,
                    "after": after,
                    "limit": limit,
                },
            },
        )

    return _handler


def _extract_forward_handler(plugin):
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        message = await _resolve_message(plugin, context, arguments)
        if message is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="message_not_found",
                message="message not available",
            )

        # Read forward content from recorder DB.
        # recorder already parsed the forward at message time via
        # parse_forward_response + flatten_forward_nodes, so the
        # content_summary field already has segment descriptions
        # including [图片], [视频], [表情] etc. for non-text nodes.
        forward_messages = getattr(message, "forward_messages", []) or []
        items = [
            {
                "id": getattr(item, "id", None),
                "depth": getattr(item, "depth", 0),
                "nickname": getattr(item, "nickname", "") or "",
                "content_summary": (getattr(item, "content_summary", "") or ""),
                "forward_id": getattr(item, "forward_id", "") or "",
            }
            for item in forward_messages
        ]
        if items:
            logger.info(
                "extract_forward db_hit message_id=%s forward_count=%d",
                getattr(message, "message_id", ""),
                len(items),
            )
            return ToolResponse(
                status="ok",
                data={"forward_messages": items, "source": "recorder"},
            )

        raw_message = str(getattr(message, "raw_message", "") or "")
        forward_id = _extract_forward_id(raw_message)
        if not forward_id:
            return ToolResponse(
                status="ok",
                data={"forward_messages": [], "source": "recorder"},
            )

        # The forward message's QQ message_id equals the forward_id.
        # The recorder may have already stored it with parsed inline
        # nodes — try the DB before calling the (usually-failing) API.
        fwd_message = await plugin._bridge.get_message(forward_id)
        if fwd_message is not None:
            fwd_children = getattr(fwd_message, "forward_messages", []) or []
            if fwd_children:
                items = [
                    {
                        "id": getattr(item, "id", None),
                        "depth": (getattr(item, "depth", 0) or 0),
                        "nickname": str(getattr(item, "nickname", "") or ""),
                        "content_summary": (getattr(item, "content_summary", "") or ""),
                        "forward_id": str(getattr(item, "forward_id", "") or ""),
                    }
                    for item in fwd_children
                ]
                logger.info(
                    "extract_forward db_forward_lookup message_id=%s forward_id=%s forward_count=%d",  # noqa: E501
                    getattr(message, "message_id", ""),
                    forward_id,
                    len(items),
                )
                return ToolResponse(
                    status="ok",
                    data={"forward_messages": items, "source": "recorder"},
                )

        logger.info(
            "extract_forward api_fallback_start message_id=%s forward_id=%s",
            getattr(message, "message_id", ""),
            forward_id,
        )
        try:
            response = await plugin.api.qq.query.get_forward_msg(forward_id)
            flattened = _flatten_forward_response_items(response)
            if getattr(message, "id", None) is not None:
                await plugin._bridge.backfill_forward_messages(message.id, flattened)
                logger.info(
                    "extract_forward db_backfill message_id=%s forward_count=%d",
                    getattr(message, "message_id", ""),
                    len(flattened),
                )
            items = [
                {
                    "depth": int(item.get("depth", 0) or 0),
                    "nickname": str(item.get("nickname", "") or ""),
                    "content_summary": str(item.get("content_summary", "") or ""),
                    "forward_id": str(item.get("forward_id", "") or ""),
                }
                for item in flattened
            ]
        except Exception as exc:
            logger.warning(
                (
                    "extract_forward api_fallback_failed"
                    " message_id=%s forward_id=%s error=%s"
                ),
                getattr(message, "message_id", ""),
                forward_id,
                exc,
            )
            return ToolResponse(
                status="failed",
                data={"forward_messages": [], "source": "api_fallback"},
                error_code="forward_fetch_failed",
                message=str(exc),
            )
        logger.info(
            "extract_forward api_fallback_ok message_id=%s forward_count=%d",
            getattr(message, "message_id", ""),
            len(items),
        )
        return ToolResponse(
            status="ok",
            data={"forward_messages": items, "source": "api_fallback"},
        )

    return _handler


def _load_message_handler(plugin):
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        message = await _resolve_message(plugin, context, arguments)
        if message is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="message_not_found",
                message="message not available",
            )
        payload = await _message_payload(plugin._bridge, message)
        return ToolResponse(status="ok", data={"message": payload})

    return _handler


def _extract_forward_id(raw_message: str) -> str:
    import re

    match = re.search(r"\[CQ:forward,[^\]]*?\bid=([^,\]]+)", raw_message)
    return match.group(1).strip() if match else ""


async def _resolve_message(plugin, context: dict[str, Any], arguments: dict[str, Any]):
    message_id = str(arguments.get("message_id") or "")
    source_msg = context.get("source_msg")
    if not message_id:
        return source_msg
    bridge = plugin._bridge
    if bridge is None:
        return None
    return await bridge.get_message(message_id)


async def _resolve_anchor_message(
    plugin,
    context: dict[str, Any],
    arguments: dict[str, Any],
):
    anchor_kind = str(arguments.get("anchor", "current") or "current")
    if anchor_kind == "message_id":
        return await _resolve_message(plugin, context, arguments)
    return context.get("source_msg")


async def _message_payload(
    bridge,
    message,
    *,
    include_forward_preview: bool = False,
    include_vision_preview: bool = False,
) -> dict[str, Any]:
    raw = unescape_text(str(getattr(message, "raw_message", "") or ""))
    payload = {
        "message_id": str(getattr(message, "message_id", "") or ""),
        "user_id": str(getattr(message, "user_id", "") or ""),
        "sender_nickname": str(getattr(message, "sender_nickname", "") or ""),
        "sender_card": str(getattr(message, "sender_card", "") or ""),
        "chat_type": str(getattr(message, "chat_type", "") or ""),
        "chat_id": str(
            getattr(message, "group_id", "") or getattr(message, "user_id", "") or ""
        ),
        "group_id": str(getattr(message, "group_id", "") or ""),
        "timestamp": str(getattr(message, "timestamp", "") or ""),
        "raw_message": raw,
        "has_image": bool(getattr(message, "has_image", False)),
        "has_forward": bool(getattr(message, "has_forward", False)),
        "has_reply": bool(getattr(message, "has_reply", False)),
        "has_video": bool(getattr(message, "has_video", False)),
        "has_at": bool(getattr(message, "has_at", False)),
        "has_app_share": bool(getattr(message, "has_app_share", False)),
    }
    if include_forward_preview:
        forward_messages = getattr(message, "forward_messages", []) or []
        payload["forward_count"] = len(forward_messages)
        payload["forward_preview"] = [
            {
                "depth": int(getattr(item, "depth", 0) or 0),
                "nickname": str(getattr(item, "nickname", "") or ""),
                "content_summary": str(getattr(item, "content_summary", "") or ""),
            }
            for item in forward_messages[:3]
        ]
    if include_vision_preview:
        images = getattr(message, "images", []) or []
        payload["image_count"] = len(images)
        analyses = []
        if bridge is not None and getattr(message, "id", None) is not None:
            analyses = await bridge.get_image_analyses_by_message(message.id)
        payload["image_analysis_count"] = len(analyses)
        payload["image_analysis_preview"] = [
            str(getattr(item, "semantic_text", "") or "")[:200]
            for item in analyses[:2]
            if str(getattr(item, "semantic_text", "") or "").strip()
        ]
        payload["image_analysis_status"] = "ready" if analyses else "missing"
    return payload


def _flatten_forward_response_items(response: Any) -> list[dict[str, Any]]:
    nodes = parse_forward_response(response)
    return flatten_forward_nodes(nodes)
