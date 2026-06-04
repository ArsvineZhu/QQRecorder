from __future__ import annotations

import logging
from typing import Any

from plugins.qq_recorder.text_utils import unescape_text

from ..shared import load_schema
from .registry import ToolDefinition, ToolResponse

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
        max_depth = int(arguments.get("max_depth", 6) or 6)
        chain = await bridge.get_reply_chain(source_msg, max_depth=max_depth)
        return ToolResponse(
            status="ok",
            data={
                "messages": [_message_payload(item) for item in chain],
                "root_message_id": str(chain[-1].message_id) if chain else None,
            },
        )

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
        limit = int(arguments.get("limit", 12) or 12)
        since_minutes = int(arguments.get("since_minutes", 30) or 30)
        items = await bridge.get_recent_window(
            chat_type,
            chat_id,
            limit=limit,
            since_minutes=since_minutes,
            before_or_at=getattr(source_msg, "timestamp", None),
        )
        return ToolResponse(
            status="ok",
            data={"messages": [_message_payload(item) for item in items]},
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
        return ToolResponse(
            status="ok",
            data={"forward_messages": items, "source": "recorder"},
        )

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


def _message_payload(message) -> dict[str, Any]:
    raw = unescape_text(str(getattr(message, "raw_message", "") or ""))
    return {
        "message_id": str(getattr(message, "message_id", "") or ""),
        "user_id": str(getattr(message, "user_id", "") or ""),
        "chat_type": str(getattr(message, "chat_type", "") or ""),
        "group_id": str(getattr(message, "group_id", "") or ""),
        "timestamp": str(getattr(message, "timestamp", "") or ""),
        "raw_message": raw,
        "has_image": bool(getattr(message, "has_image", False)),
        "has_forward": bool(getattr(message, "has_forward", False)),
    }
