from types import SimpleNamespace
from typing import Any

from .compat import import_sibling_plugin_module
from .config import ReplyPluginSettings
from .context_render import (
    extract_forward_id,
    has_forward_marker,
    message_view,
    raw_message_text,
)

_forward_parser = import_sibling_plugin_module("qq_recorder.forward_parser")
flatten_forward_nodes = _forward_parser.flatten_forward_nodes
parse_forward_response = _forward_parser.parse_forward_response


async def hydrate_legacy_forward_messages(
    messages: list[Any], runtime_api, settings: ReplyPluginSettings
) -> list[Any]:
    result = []
    for message in messages:
        result.append(
            await hydrate_legacy_forward_message(message, runtime_api, settings)
        )
    return result


async def hydrate_legacy_forward_message(
    message, runtime_api, settings: ReplyPluginSettings
):
    if message is None:
        return None
    if not has_forward_marker(message):
        return message
    forwards = list(getattr(message, "forward_messages", []) or [])
    if forwards:
        return message
    forward_id = extract_forward_id(raw_message_text(message))
    if not forward_id or runtime_api is None:
        return message_view(message, has_forward=True)
    try:
        response = await runtime_api.qq.query.get_forward_msg(forward_id)
        nodes = parse_forward_response(
            response, max_depth=settings.context.forward_max_items
        )
        flattened = flatten_forward_nodes(nodes)
    except Exception:
        flattened = []
    if not flattened:
        return message_view(message, has_forward=True)
    hydrated_forwards = [
        SimpleNamespace(
            id=index + 1,
            depth=item.get("depth", 0),
            nickname=item.get("nickname", ""),
            user_id=item.get("user_id", ""),
            content_summary=item.get("content_summary", ""),
            forward_id=item.get("forward_id", ""),
        )
        for index, item in enumerate(flattened)
    ]
    return message_view(
        message,
        has_forward=True,
        forward_messages=hydrated_forwards,
    )
