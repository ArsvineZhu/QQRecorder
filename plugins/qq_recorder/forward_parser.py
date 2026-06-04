from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .text_utils import escape_text


@dataclass
class ForwardNode:
    user_id: str
    nickname: str
    depth: int
    content_summary: str
    children: list[ForwardNode] = field(default_factory=list)
    forward_id: str = ""


_SEGMENT_LABELS: dict[str, str] = {
    "image": "[图片]",
    "video": "[视频]",
    "face": "[表情]",
    "reply": "[回复]",
    "forward": "[转发消息]",
    "json": "[卡片消息]",
    "file": "[文件]",
    "record": "[语音]",
    "location": "[位置]",
    "music": "[音乐分享]",
    "share": "[分享]",
    "poke": "[戳一戳]",
    "gift": "[礼物]",
    "redbag": "[红包]",
    "wallet": "[转账]",
}


def _segment_text(segment: dict) -> str:
    """Convert a single forward segment to a text summary."""
    seg_type = segment.get("type", "")
    data = segment.get("data", {}) or {}
    if seg_type == "text":
        return data.get("text", "")
    if label := _SEGMENT_LABELS.get(seg_type):
        return label
    if seg_type == "at":
        uid = data.get("qq", "")
        return f"@{uid}" if uid else "[@]"
    if seg_type and seg_type != "node":
        return f"[{seg_type}]"
    return ""


def extract_text_from_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            _segment_text(segment) for segment in content if isinstance(segment, dict)
        )
    return ""


def extract_nested_nodes(
    content: list[dict], depth: int, max_depth: int
) -> list[ForwardNode]:
    if not isinstance(content, list):
        return []
    nested = []
    for segment in content:
        if isinstance(segment, dict) and segment.get("type") == "node":
            node_data = segment.get("data", {})
            parsed = _parse_single_node(node_data, depth, max_depth)
            nested.append(parsed)
    return nested


def _parse_single_node(data: dict, depth: int, max_depth: int) -> ForwardNode:
    user_id = str(data.get("user_id", ""))
    nickname = data.get("nickname", "")
    forward_id = str(data.get("forward_id", ""))
    content = data.get("content")

    content_summary = escape_text(extract_text_from_content(content))

    children: list[ForwardNode] = []
    if depth < max_depth and isinstance(content, list):
        children = extract_nested_nodes(content, depth + 1, max_depth)

    return ForwardNode(
        user_id=user_id,
        nickname=nickname,
        depth=depth,
        content_summary=content_summary,
        children=children,
        forward_id=forward_id,
    )


def parse_forward_nodes(
    nodes_data: list[dict], depth: int = 0, max_depth: int = 10
) -> list[ForwardNode]:
    if not nodes_data:
        return []
    result = []
    for node_dict in nodes_data:
        if not isinstance(node_dict, dict):
            continue
        if node_dict.get("type") != "node":
            continue
        data = node_dict.get("data", {})
        parsed = _parse_single_node(data, depth, max_depth)
        result.append(parsed)
    return result


def flatten_forward_nodes(nodes: list[ForwardNode]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(
            {
                "user_id": node.user_id,
                "nickname": node.nickname,
                "depth": node.depth,
                "content_summary": node.content_summary,
                "parent_forward_id": None,
                "forward_id": node.forward_id,
            }
        )
        if node.children:
            result.extend(flatten_forward_nodes(node.children))
    return result


def parse_forward_response(
    response_data: Any, max_depth: int = 10
) -> list[ForwardNode]:
    # 支持 ForwardMessageData (Pydantic 模型，有 .messages 属性) 和 dict
    if hasattr(response_data, "messages"):
        messages = response_data.messages
    else:
        messages = response_data.get("messages", [])
    return parse_forward_nodes(messages, depth=0, max_depth=max_depth)
