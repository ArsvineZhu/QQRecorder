from __future__ import annotations

import json
import re
from typing import Any


def top(data: dict) -> dict:
    if "data" not in data:
        return {"data": data}
    return data


def sanitize_text(text: str) -> str:
    result = text
    for marker in ("SYSTEM_INSTRUCTIONS:", "FINAL_REQUIREMENT:"):
        result = result.replace(marker, f"[escaped:{marker[:-1]}]")
    return result.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


_RENDERERS: dict[str, Any] = {}


def render_evidence(
    working_context,
    labels: set[str],
    *,
    include_errors: bool = False,
    render_state: dict[str, Any] | None = None,
) -> str:
    rendered: list[str] = []
    for block in working_context.evidence:
        if block.label not in labels:
            if not (include_errors and block.kind == "tool_error"):
                continue
        text = render_block(block, render_state=render_state)
        if text:
            rendered.append(text)
    return "\n".join(rendered)


def render_block(block, *, render_state: dict[str, Any] | None = None) -> str:
    label = block.label or ""
    content = str(block.content or "")

    if block.kind == "tool_error":
        return f"- **工具错误 `{label}`**：{sanitize_text(content[:800])}"

    try:
        payload = json.loads(content) if content else {}
    except (json.JSONDecodeError, TypeError):
        return sanitize_text(content[:2000])

    if not isinstance(payload, dict):
        return sanitize_text(content[:2000])

    payload = top(payload)
    failed = render_failed_tool_response(label, payload)
    if failed:
        return failed
    renderer = _RENDERERS.get(label)
    if renderer:
        return renderer(payload, render_state or {})
    return f"```json\n{sanitize_text(content[:2000])}\n```"


def render_failed_tool_response(label: str, payload: dict) -> str:
    if str(payload.get("status", "") or "") != "failed":
        return ""
    error_code = str(payload.get("error_code", "") or "unknown_error")
    message = str(payload.get("message", "") or "工具返回失败")
    retryable = payload.get("retryable", False)
    retry_text = "可重试" if retryable else "不可重试"
    return (
        f"- **工具 `{label}` 失败**：{sanitize_text(message)} "
        f"(`{error_code}`, {retry_text})"
    )


def renderer(name: str):
    def wrapper(fn):
        _RENDERERS[name] = fn
        return fn

    return wrapper


@renderer("track_reply")
def render_track_reply(data: dict, render_state: dict[str, Any]) -> str:
    status = str(data.get("status", "") or "")
    error_code = str(data.get("error_code", "") or "")
    message = str(data.get("message", "") or "")
    messages = data.get("data", {}).get("messages", []) or []
    if not messages:
        if status == "failed" or error_code:
            detail = message or "引用链为空，不要重复调用 track_reply。"
            return f"- **引用链不可继续查询**：{sanitize_text(detail)}"
        return "- **引用链为空**：这条链已经查完，不要重复调用 `track_reply`。"
    lines: list[str] = []
    for msg in messages:
        raw = semanticize_message_text(
            str(msg.get("raw_message", "") or ""),
            bot_id=str(render_state.get("bot_id", "") or ""),
            id_to_name=render_state.get("id_to_name", {}),
            assistant_name=str(render_state.get("assistant_name", "Grok") or "Grok"),
        )
        time_part = message_time_label(msg)
        sender = message_sender_label(msg)
        lines.append(f"- [{time_part}] `{sanitize_text(sender)}`：{sanitize_text(raw)}")
    root = str(data.get("data", {}).get("root_message_id") or "")
    if root:
        lines.append(f"- 根消息 ID：`{root}`")
    return "\n".join(lines)


@renderer("load_context")
def render_load_context(data: dict, render_state: dict[str, Any]) -> str:
    messages = data.get("data", {}).get("messages", []) or []
    replay_message_ids = set(render_state.get("replay_message_ids", set()) or set())
    if replay_message_ids:
        messages = [
            item
            for item in messages
            if str(item.get("message_id", "") or "") not in replay_message_ids
        ]
    if not messages:
        return "- **上下文为空**"

    by_date: dict[str, list[dict]] = {}
    for msg in messages:
        ts = str(msg.get("timestamp", "") or "")
        date_key = ts[:10] if len(ts) >= 10 else "unknown"
        by_date.setdefault(date_key, []).append(msg)

    lines: list[str] = []
    for date_key in sorted(by_date.keys()):
        if len(by_date) > 1:
            lines.append(f"### {date_key}")
        lines.extend(render_grouped_context_messages(by_date[date_key], render_state))
    return "\n".join(lines)


@renderer("load_message")
def render_load_message(data: dict, render_state: dict[str, Any]) -> str:
    message = data.get("data", {}).get("message", {}) or {}
    if not isinstance(message, dict) or not message:
        return "- **指定消息为空**"
    rendered = render_context_message_line(
        message,
        render_state=render_state,
        truncate=False,
        include_sender=True,
    )
    message_id = str(message.get("message_id", "") or "unknown")
    return "\n".join(
        ["### 指定消息", f"- msg-id：`{sanitize_text(message_id)}`", rendered]
    )


@renderer("query_chat_history")
def render_query_chat_history(data: dict, render_state: dict[str, Any]) -> str:
    query = data.get("data", {}).get("query", {}) or {}
    messages = data.get("data", {}).get("messages", []) or []
    if not messages:
        return "- **历史检索为空**"
    lines = ["### 历史检索结果"]
    keyword = str(query.get("keyword", "") or "").strip()
    user_id = str(query.get("user_id", "") or "").strip()
    summary_bits = []
    if keyword:
        summary_bits.append(f"关键词：`{sanitize_text(keyword)}`")
    if user_id:
        summary_bits.append(f"用户：`{sanitize_text(user_id)}`")
    if summary_bits:
        lines.append(f"- {'；'.join(summary_bits)}")
    by_date: dict[str, list[dict]] = {}
    for msg in messages:
        ts = str(msg.get("timestamp", "") or "")
        date_key = ts[:10] if len(ts) >= 10 else "unknown"
        by_date.setdefault(date_key, []).append(msg)
    for date_key in sorted(by_date.keys()):
        if len(by_date) > 1:
            lines.append(f"#### {date_key}")
        lines.extend(render_grouped_context_messages(by_date[date_key], render_state))
    return "\n".join(lines)


@renderer("extract_forward")
def render_extract_forward(data: dict, _render_state: dict[str, Any]) -> str:
    items = data.get("data", {}).get("forward_messages", []) or []
    if not items:
        return "- **合并转发为空**"
    lines: list[str] = ["### 合并转发内容"]
    for item in items:
        nick = str(item.get("nickname", "") or "unknown")
        summary = str(item.get("content_summary", "") or "")
        depth = int(item.get("depth", 0))
        indent = "  " * depth
        lines.append(f"{indent}- **{sanitize_text(nick)}**：{sanitize_text(summary)}")
    return "\n".join(lines)


@renderer("load_profile")
def render_load_profile(data: dict, _render_state: dict[str, Any]) -> str:
    profile = data.get("data", {}) or {}
    if not profile:
        return "- **用户档案**：无用户档案，只有空白 ID"
    labels = {
        "username": "昵称",
        "preferred_name": "偏好称呼",
        "group_nickname": "群昵称",
        "group_instruction": "群聊指令",
        "private_instruction": "私聊指令",
        "language_style": "语言风格偏好",
        "habit_preferences": "习惯偏好",
    }
    lines: list[str] = ["### 用户档案"]
    for key, value in profile.items():
        label = labels.get(key, key)
        if isinstance(value, list):
            safe = ", ".join(sanitize_text(str(v)) for v in value if v)
            if safe:
                lines.append(f"- **{label}**：{safe}")
        elif value:
            lines.append(f"- **{label}**：{sanitize_text(str(value))}")
    return "\n".join(lines) if len(lines) > 1 else "- **用户档案**：无用户档案"


@renderer("read_picture")
def render_read_picture(data: dict, _render_state: dict[str, Any]) -> str:  # noqa: C901
    content = data.get("data", {}) or {}
    lines: list[str] = ["### 图片分析"]
    if content.get("image_type"):
        lines.append(f"- **类型**：{sanitize_text(str(content['image_type']))}")
    if content.get("confidence"):
        lines.append(f"- **置信度**：{sanitize_text(str(content['confidence']))}")
    lit = content.get("literal_content", {}) or {}
    if lit.get("summary"):
        lines.append(f"- **概述**：{sanitize_text(str(lit['summary'])[:300])}")
    if lit.get("scene"):
        lines.append(f"- **场景**：{sanitize_text(str(lit['scene'])[:120])}")
    if lit.get("visible_objects"):
        objs = lit["visible_objects"]
        if isinstance(objs, list):
            objs = "、".join(str(o) for o in objs)
        lines.append(f"- **物品**：{sanitize_text(str(objs)[:200])}")
    if lit.get("visible_people"):
        people = lit["visible_people"]
        if isinstance(people, list):
            people = "、".join(str(p) for p in people)
        lines.append(f"- **人物**：{sanitize_text(str(people)[:200])}")
    if lit.get("ocr_text"):
        ocr = lit["ocr_text"]
        if isinstance(ocr, list):
            ocr = " | ".join(str(t) for t in ocr)
        lines.append(f"- **文字**：{sanitize_text(str(ocr)[:300])}")
    sem = content.get("semantic_interpretation", {}) or {}
    if sem.get("main_meaning"):
        lines.append(f"- **含义**：{sanitize_text(str(sem['main_meaning'])[:300])}")
    if sem.get("implied_message"):
        lines.append(f"- **暗示**：{sanitize_text(str(sem['implied_message'])[:200])}")
    if sem.get("text_image_relation"):
        lines.append(
            f"- **图文关系**：{sanitize_text(str(sem['text_image_relation'])[:150])}"
        )
    if sem.get("meme_or_cultural_reference"):
        cultural_reference = sanitize_text(str(sem["meme_or_cultural_reference"])[:150])
        lines.append(f"- **梗/引用**：{cultural_reference}")
    aff = content.get("affective_reading", {}) or {}
    tone_raw = aff.get("tone", []) or []
    if isinstance(tone_raw, list) and tone_raw:
        tones = []
        for t in tone_raw:
            if isinstance(t, dict):
                label = str(t.get("label", "") or "")
                intensity = float(t.get("intensity", 0) or 0)
                if label and intensity > 0:
                    tones.append(f"{label}({intensity:.1f})")
        if tones:
            lines.append(f"- **语气**：{'、'.join(tones[:4])}")
    msg_text = content.get("message_text", "")
    if msg_text:
        lines.append(f"- **附带消息**：{sanitize_text(str(msg_text)[:200])}")
    return "\n".join(lines)


@renderer("read_video")
def render_read_video(data: dict, _render_state: dict[str, Any]) -> str:  # noqa: C901
    content = data.get("data", {}) or {}
    lines: list[str] = ["### 视频分析"]
    if content.get("video_type"):
        lines.append(f"- **类型**：{sanitize_text(str(content['video_type']))}")
    if content.get("duration_summary"):
        lines.append(
            f"- **时长**：{sanitize_text(str(content['duration_summary'])[:60])}"
        )
    if content.get("visual_summary"):
        lines.append(
            f"- **画面**：{sanitize_text(str(content['visual_summary'])[:300])}"
        )
    if content.get("audio_or_speech_summary"):
        audio_summary = sanitize_text(str(content["audio_or_speech_summary"])[:200])
        lines.append(f"- **音频**：{audio_summary}")
    events = content.get("key_events", []) or []
    if isinstance(events, list) and events:
        summaries = []
        for ev in events[:3]:
            if isinstance(ev, dict):
                tr = str(ev.get("time_range", "") or "")
                desc = str(ev.get("event", "") or "")
                if tr and desc:
                    summaries.append(f"{tr} {desc}")
                elif desc:
                    summaries.append(desc)
        if summaries:
            lines.append(f"- **关键事件**：{sanitize_text('; '.join(summaries))}")
    if content.get("semantic_meaning"):
        lines.append(
            f"- **含义**：{sanitize_text(str(content['semantic_meaning'])[:300])}"
        )
    if content.get("contextual_meaning"):
        contextual_meaning = sanitize_text(str(content["contextual_meaning"])[:200])
        lines.append(f"- **上下文含义**：{contextual_meaning}")
    if content.get("visible_text"):
        vt = content["visible_text"]
        if isinstance(vt, list):
            vt = " | ".join(str(t) for t in vt)
        lines.append(f"- **文字**：{sanitize_text(str(vt)[:200])}")
    if content.get("confidence"):
        lines.append(f"- **置信度**：{sanitize_text(str(content['confidence']))}")
    aff = content.get("affective_reading", {}) or {}
    tone_raw = aff.get("tone", []) or []
    if isinstance(tone_raw, list) and tone_raw:
        tones = []
        for t in tone_raw:
            if isinstance(t, dict):
                label = str(t.get("label", "") or "")
                intensity = float(t.get("intensity", 0) or 0)
                if label and intensity > 0:
                    tones.append(f"{label}({intensity:.1f})")
        if tones:
            lines.append(f"- **语气**：{'、'.join(tones[:4])}")
    msg_text = content.get("message_text", "")
    if msg_text:
        lines.append(f"- **附带消息**：{sanitize_text(str(msg_text)[:200])}")
    return "\n".join(lines)


def build_render_state(working_context, settings) -> dict[str, Any]:
    context = working_context.context
    id_to_name: dict[str, str] = {}
    name_to_id: dict[str, str] = {}
    add_roster_entry(
        id_to_name,
        name_to_id,
        str(context.user_id or ""),
        str(context.current_sender or ""),
    )
    for block in working_context.evidence:
        try:
            payload = json.loads(str(block.content or ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        top_data = top(payload).get("data", {}) or {}
        messages = top_data.get("messages", []) or []
        if isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict):
                    collect_roster_entry_from_message(msg, id_to_name, name_to_id)
        message = top_data.get("message", {}) or {}
        if isinstance(message, dict):
            collect_roster_entry_from_message(message, id_to_name, name_to_id)
    roster = sorted(name_to_id.items(), key=lambda item: item[1])
    return {
        "bot_id": str(context.bot_id or ""),
        "assistant_name": assistant_name(settings),
        "id_to_name": id_to_name,
        "roster": roster,
        "context_message_preview_chars": int(
            getattr(settings.prompt, "context_message_preview_chars", 280) or 280
        ),
        "replay_message_ids": set(
            getattr(working_context, "replay_message_ids", set()) or set()
        ),
    }


def add_roster_entry(
    id_to_name: dict[str, str],
    name_to_id: dict[str, str],
    user_id: str,
    display_name: str,
) -> None:
    clean_id = user_id.strip()
    clean_name = display_name.strip()
    if not clean_id or not clean_name or clean_name == clean_id:
        return
    id_to_name.setdefault(clean_id, clean_name)
    name_to_id.setdefault(clean_name, clean_id)


def collect_roster_entry_from_message(
    message: dict[str, Any],
    id_to_name: dict[str, str],
    name_to_id: dict[str, str],
) -> None:
    user_id = str(message.get("user_id", "") or "")
    display_name = (
        str(message.get("sender_card", "") or "").strip()
        or str(message.get("sender_nickname", "") or "").strip()
        or str(message.get("nickname", "") or "").strip()
    )
    add_roster_entry(id_to_name, name_to_id, user_id, display_name)


def render_group_roster(roster: list[tuple[str, str]]) -> str:
    if not roster:
        return ""
    return "\n".join(
        f"- `{sanitize_text(name)}` → `{sanitize_text(user_id)}`"
        for name, user_id in roster
    )


def semanticize_message_text(
    raw_message: str,
    *,
    bot_id: str,
    id_to_name: dict[str, str],
    assistant_name: str,
) -> str:
    text = str(raw_message or "")
    if not text:
        return ""
    pieces: list[str] = []
    cursor = 0
    for match in re.finditer(r"\[CQ:([a-zA-Z0-9_]+)(?:,([^\]]*))?\]", text):
        prefix = text[cursor : match.start()].strip()
        if prefix:
            pieces.append(prefix)
        pieces.append(
            render_cq_segment(
                match.group(1),
                match.group(2) or "",
                bot_id=bot_id,
                id_to_name=id_to_name,
                assistant_name=assistant_name,
            )
        )
        cursor = match.end()
    suffix = text[cursor:].strip()
    if suffix:
        pieces.append(suffix)
    return " ".join(piece for piece in pieces if piece).strip()


def render_cq_segment(
    segment_type: str,
    raw_args: str,
    *,
    bot_id: str,
    id_to_name: dict[str, str],
    assistant_name: str,
) -> str:
    args = parse_cq_args(raw_args)

    def _reply():
        reply_id = str(args.get("id", "") or "").strip()
        return f"[回复:{reply_id}]" if reply_id else "[回复]"

    def _at():
        target = str(args.get("qq", "") or args.get("target_user_id", "") or "").strip()
        if not target:
            return "@某人"
        if target == bot_id:
            return f"@{assistant_name}"
        return f"@{id_to_name.get(target, target)}"

    def _image():
        details: list[str] = []
        image_type = infer_image_type(args)
        if image_type:
            details.append(f"类型:{image_type}")
        file_size = str(args.get("file_size", "") or "").strip()
        if file_size:
            details.append(f"大小:{file_size}")
        return f"[图片:{','.join(details)}]" if details else "[图片]"

    def _face():
        face_name = str(args.get("text", "") or args.get("name", "") or "").strip()
        return f"[表情:{face_name}]" if face_name else "[表情]"

    handlers = {
        "reply": _reply,
        "at": _at,
        "image": _image,
        "face": _face,
        "forward": lambda: "[合并转发]",
        "video": lambda: "[视频]",
    }
    handler = handlers.get(segment_type)
    if handler:
        return handler()
    return f"[{segment_type}]"


def parse_cq_args(raw_args: str) -> dict[str, str]:
    args: dict[str, str] = {}
    for part in str(raw_args or "").split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        args[key.strip()] = value.strip()
    return args


def infer_image_type(args: dict[str, str]) -> str:
    for key in ("file", "url"):
        value = str(args.get(key, "") or "").strip()
        match = re.search(r"\.([a-zA-Z0-9]+)(?:$|[?&,])", value)
        if match:
            return match.group(1).lower()
    return ""


def message_time_label(message: dict[str, Any]) -> str:
    ts = str(message.get("timestamp", "") or "")
    return ts[11:19] if len(ts) >= 19 else ts or "unknown"


def message_sender_label(message: dict[str, Any]) -> str:
    for key in ("sender_card", "sender_nickname", "nickname"):
        value = str(message.get(key, "") or "").strip()
        if value:
            return value
    return str(message.get("user_id", "") or "unknown").strip() or "unknown"


def assistant_name(settings) -> str:
    return str(getattr(settings.prompt, "assistant_name", "Grok") or "Grok").strip()


def render_grouped_context_messages(
    messages: list[dict[str, Any]],
    render_state: dict[str, Any],
) -> list[str]:
    grouped_lines: list[str] = []
    current_sender: str | None = None
    current_lines: list[str] = []
    for message in messages:
        sender = message_sender_label(message)
        line = render_context_message_line(
            message,
            render_state=render_state,
            truncate=True,
        )
        if sender != current_sender:
            if current_sender is not None:
                grouped_lines.append(f"- `{sanitize_text(current_sender)}`")
                grouped_lines.extend(current_lines)
            current_sender = sender
            current_lines = [f"  {line}"]
            continue
        current_lines.append(f"  {line}")
    if current_sender is not None:
        grouped_lines.append(f"- `{sanitize_text(current_sender)}`")
        grouped_lines.extend(current_lines)
    return grouped_lines


def render_context_message_line(
    message: dict[str, Any],
    *,
    render_state: dict[str, Any],
    truncate: bool,
    include_sender: bool = False,
) -> str:
    time_part = message_time_label(message)
    sender = message_sender_label(message)
    raw = semanticize_message_text(
        str(message.get("raw_message", "") or ""),
        bot_id=str(render_state.get("bot_id", "") or ""),
        id_to_name=render_state.get("id_to_name", {}),
        assistant_name=str(render_state.get("assistant_name", "Grok") or "Grok"),
    )
    if truncate:
        raw = truncate_context_message(
            raw,
            str(message.get("message_id", "") or ""),
            int(render_state.get("context_message_preview_chars", 280) or 280),
        )
    tags = []
    if (
        bool(message.get("has_image", False))
        and "[图片" not in raw
        and "（图片）" not in raw
    ):
        tags.append("图片")
    if bool(message.get("has_forward", False)) and "[合并转发]" not in raw:
        tags.append("转发")
    forward_preview = message.get("forward_preview", []) or []
    if forward_preview:
        preview = str(forward_preview[0].get("content_summary", "") or "").strip()
        if preview:
            tags.append(f"转发摘要:{sanitize_text(preview[:40])}")
    image_preview = message.get("image_analysis_preview", []) or []
    if image_preview:
        tags.append(f"图像摘要:{sanitize_text(str(image_preview[0])[:40])}")
    suffix = f"（{', '.join(tags)}）" if tags else ""
    if include_sender:
        return (
            f"- [{time_part}] `{sanitize_text(sender)}`：{sanitize_text(raw)}{suffix}"
        )
    return f"[{time_part}] {sanitize_text(raw)}{suffix}"


def truncate_context_message(text: str, message_id: str, preview_chars: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= preview_chars:
        return clean
    suffix = f"……[已截断，msg-id: `{message_id or 'unknown'}`]"
    allowed = max(0, preview_chars - len(suffix))
    return clean[:allowed].rstrip() + suffix
