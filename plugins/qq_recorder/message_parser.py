from dataclasses import dataclass
import json
from typing import List, Dict


@dataclass
class ImageInfo:
    file_url: str
    file_unique: str
    file_size: int


@dataclass
class ReplyInfo:
    reply_to_message_id: str


@dataclass
class AtInfo:
    target_user_id: str


@dataclass
class ParsedMessage:
    text: str
    has_image: bool
    has_reply: bool
    has_forward: bool
    has_at: bool
    segments: List[Dict]
    images: List[ImageInfo]
    replies: List[ReplyInfo]
    at_mentions: List[AtInfo]
    forward_ids: List[str]


ALLOWED_SEGMENT_TYPES = {"text", "image", "at", "reply", "forward", "face"}


def extract_text(segments: List[Dict]) -> str:
    text_parts = []
    for seg in segments:
        if seg["type"] == "text":
            text_parts.append(seg["data"].get("text", ""))
    return "".join(text_parts)


def extract_images(segments: List[Dict]) -> List[ImageInfo]:
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
            images.append(ImageInfo(file_url, file_unique, file_size))
    return images


def extract_replies(segments: List[Dict]) -> List[ReplyInfo]:
    replies = []
    for seg in segments:
        if seg["type"] == "reply":
            reply_id = seg["data"].get("id", "")
            replies.append(ReplyInfo(reply_id))
    return replies


def extract_at_mentions(segments: List[Dict]) -> List[AtInfo]:
    ats = []
    for seg in segments:
        if seg["type"] == "at":
            qq = str(seg["data"].get("qq", ""))
            ats.append(AtInfo(qq))
    return ats


def extract_forward_ids(segments: List[Dict]) -> List[str]:
    forward_ids = []
    for seg in segments:
        if seg["type"] == "forward":
            forward_id = seg["data"].get("id", "").strip()
            if forward_id:
                forward_ids.append(forward_id)
    return forward_ids


def build_segments_data(message_segments: List[Dict]) -> List[Dict]:
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


def parse_message(message_segments: List[Dict]) -> ParsedMessage:
    text = extract_text(message_segments)
    images = extract_images(message_segments)
    replies = extract_replies(message_segments)
    at_mentions = extract_at_mentions(message_segments)
    forward_ids = extract_forward_ids(message_segments)
    segments = build_segments_data(message_segments)

    return ParsedMessage(
        text=text,
        has_image=len(images) > 0,
        has_reply=len(replies) > 0,
        has_forward=len(forward_ids) > 0,
        has_at=len(at_mentions) > 0,
        segments=segments,
        images=images,
        replies=replies,
        at_mentions=at_mentions,
        forward_ids=forward_ids,
    )
