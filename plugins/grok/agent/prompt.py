from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _top(data: dict) -> dict:
    """Normalize to ``{"data": {...}}`` wrapper format.

    ``_normalize_result_payload`` stores only the inner ``data`` dict.
    Renderers expect ``data["data"]["messages"]``. Re-wrap if needed.
    """
    if "data" not in data:
        return {"data": data}
    return data


def render_system_prompt(settings, *, values: dict[str, str]) -> str:
    template_path = _resolve_template_path(settings.prompt.system_template_path)
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_model_messages(working_context, settings) -> list[dict[str, str]]:
    system = render_system_prompt(settings, values={})
    user = _build_user_content(working_context)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_working_context(working_context) -> str:
    lines = [
        f"chat_type={working_context.context.chat_type}",
        f"chat_id={working_context.context.chat_id}",
        f"user_id={working_context.context.user_id}",
        f"trigger_reason={working_context.context.trigger_reason}",
        f"parser_version={working_context.context.parser_version}",
        f"context_version={working_context.context.context_version}",
        f"profile_version={working_context.context.profile_version}",
        f"current_message={_sanitize_text(working_context.context.current_message)}",
    ]
    for block in working_context.evidence:
        lines.append(f"[{block.kind}] {block.label}: {_sanitize_text(block.content)}")
    return "\n".join(lines)


def _resolve_template_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent.parent / value


def _sanitize_text(text: str) -> str:
    """Escape prompt-injection markers and flatten multiline text to single line."""
    result = text
    for marker in ("SYSTEM_INSTRUCTIONS:", "FINAL_REQUIREMENT:"):
        result = result.replace(marker, f"[escaped:{marker[:-1]}]")
    # Flatten newlines to avoid breaking the prompt structure
    result = result.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return result.strip()


def _build_user_content(working_context) -> str:
    context = working_context.context
    parts = [
        "【会话信息】\n"
        f"会话类型：{context.chat_type}\n"
        f"当前时间：{context.current_time}\n"
        f"发送者：{context.current_sender or context.user_id} (ID: {context.user_id})"
    ]

    quoted = _render_evidence(working_context, {"track_reply"})
    if quoted:
        parts.append(f"【引用消息】\n{quoted}")

    recent = _render_evidence(
        working_context,
        {"load_context", "extract_forward", "load_profile"},
        include_errors=True,
    )
    if recent:
        parts.append(f"【相关消息】\n{recent}")

    visual = _render_evidence(working_context, {"read_picture", "read_video"})
    if visual:
        parts.append(f"【视觉分析】\n{visual}")

    reply_instruction = str(getattr(context, "group_instruction", "") or "")
    if not reply_instruction or reply_instruction == "group":
        reply_instruction = (
            (
                "回复要短、快、有判断，适合插入群聊。不要长篇解释；"
                "除非用户明确要求详细分析，否则控制在 1 到 4 句话。"
            )
            if context.chat_type == "group"
            else (
                "回复更完整，但仍然保持直接、有判断、机智。能给结论就先给结论，必要时再解释。"
            )
        )
    parts.append(f"【回复要求】\n{reply_instruction}")
    parts.append(f"【当前消息】\n{_sanitize_text(context.current_message)}")
    parts.append("请生成一条可以直接发送到 IM 平台的回复。")
    return "\n\n".join(parts)


# ── Semantic rendering per tool ──────────────────────────────────


def _render_evidence(
    working_context,
    labels: set[str],
    *,
    include_errors: bool = False,
) -> str:
    """Render tool results as semantic text blocks, not raw JSON."""
    rendered: list[str] = []
    for block in working_context.evidence:
        if block.label not in labels:
            if not (include_errors and block.kind == "tool_error"):
                continue
        text = _render_block(block)
        if text:
            rendered.append(text)
    return "\n".join(rendered)


def _render_block(block) -> str:
    label = block.label or ""
    content = str(block.content or "")

    if block.kind == "tool_error":
        return f"[错误] {label}: {_sanitize_text(content[:800])}"

    try:
        payload = json.loads(content) if content else {}
    except (json.JSONDecodeError, TypeError):
        return _sanitize_text(content[:2000])

    if not isinstance(payload, dict):
        return _sanitize_text(content[:2000])

    payload = _top(payload)
    renderer = _RENDERERS.get(label)
    if renderer:
        return renderer(payload)
    return _sanitize_text(content[:2000])


_RENDERERS: dict[str, Any] = {}


def _renderer(name: str):
    """Decorator to register a renderer for a tool label."""

    def wrapper(fn):
        _RENDERERS[name] = fn
        return fn

    return wrapper


@_renderer("track_reply")
def _render_track_reply(data: dict) -> str:
    messages = data.get("data", {}).get("messages", []) or []
    if not messages:
        return "(引用链为空)"
    lines: list[str] = []
    for msg in messages:
        ts = str(msg.get("timestamp", "") or "")
        uid = str(msg.get("user_id", "") or "")
        raw = str(msg.get("raw_message", "") or "")
        lines.append(f"[{ts}] [{uid}] {_sanitize_text(raw)}")
    root = str(data.get("data", {}).get("root_message_id") or "")
    if root:
        lines.append(f"→ 根消息: {root}")
    return "\n".join(lines)


@_renderer("load_context")
def _render_load_context(data: dict) -> str:
    messages = data.get("data", {}).get("messages", []) or []
    if not messages:
        return "(上下文为空)"

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for msg in messages:
        ts = str(msg.get("timestamp", "") or "")
        date_key = ts[:10] if len(ts) >= 10 else "unknown"
        by_date.setdefault(date_key, []).append(msg)

    lines: list[str] = []
    for date_key in sorted(by_date.keys()):
        msgs = by_date[date_key]
        is_recent = date_key == sorted(by_date.keys())[-1] if len(by_date) > 1 else True
        if len(by_date) > 1:
            if is_recent:
                lines.append("[最近]")
            else:
                lines.append(f"[{date_key}]")
        for msg in msgs:
            ts = str(msg.get("timestamp", "") or "")
            time_part = ts[11:19] if len(ts) >= 19 else ts
            uid = str(msg.get("user_id", "") or "")
            raw = str(msg.get("raw_message", "") or "")
            has_img = bool(msg.get("has_image", False))
            has_fwd = bool(msg.get("has_forward", False))
            suffix = ""
            if has_img:
                suffix += " [图片]"
            if has_fwd:
                suffix += " [转发]"
            lines.append(f"  [{time_part}] [{uid}] {_sanitize_text(raw)}{suffix}")
    return "\n".join(lines)


@_renderer("extract_forward")
def _render_extract_forward(data: dict) -> str:
    items = data.get("data", {}).get("forward_messages", []) or []
    if not items:
        return "(转发为空)"
    lines: list[str] = ["[合并转发开始]"]
    for item in items:
        nick = str(item.get("nickname", "") or "")
        summary = str(item.get("content_summary", "") or "")
        depth = int(item.get("depth", 0))
        indent = "  " * depth
        lines.append(f"{indent}[{nick}] {summary}")
    lines.append("[合并转发结束]")
    return "\n".join(lines)


@_renderer("load_profile")
def _render_load_profile(data: dict) -> str:
    profile = data.get("data", {}) or {}
    if not profile:
        return "(无用户档案，只有空白 ID)"
    labels = {
        "username": "昵称",
        "preferred_name": "偏好称呼",
        "group_nickname": "群昵称",
        "group_instruction": "群聊指令",
        "private_instruction": "私聊指令",
        "language_style": "语言风格",
        "habit_preferences": "习惯偏好",
    }
    lines: list[str] = []
    for key, value in profile.items():
        label = labels.get(key, key)
        if isinstance(value, list):
            safe = ", ".join(_sanitize_text(str(v)) for v in value if v)
            lines.append(f"  {label}: {safe}")
        elif value:
            lines.append(f"  {label}: {_sanitize_text(str(value))}")
    return "\n用户档案:\n" + "\n".join(lines) if lines else "(无用户档案)"


@_renderer("read_picture")
def _render_read_picture(data: dict) -> str:  # noqa: C901
    content = data.get("data", {}) or {}
    lines: list[str] = ["[图片分析]"]
    if content.get("image_type"):
        lines.append(f"  类型: {content['image_type']}")
    if content.get("confidence"):
        lines.append(f"  置信度: {content['confidence']}")
    lit = content.get("literal_content", {}) or {}
    if lit.get("summary"):
        lines.append(f"  概述: {lit['summary'][:300]}")
    if lit.get("scene"):
        lines.append(f"  场景: {lit['scene'][:120]}")
    if lit.get("visible_objects"):
        objs = lit["visible_objects"]
        if isinstance(objs, list):
            objs = "、".join(str(o) for o in objs)
        lines.append(f"  物品: {objs[:200]}")
    if lit.get("visible_people"):
        people = lit["visible_people"]
        if isinstance(people, list):
            people = "、".join(str(p) for p in people)
        lines.append(f"  人物: {people[:200]}")
    if lit.get("ocr_text"):
        ocr = lit["ocr_text"]
        if isinstance(ocr, list):
            ocr = " | ".join(str(t) for t in ocr)
        lines.append(f"  文字: {str(ocr)[:300]}")
    sem = content.get("semantic_interpretation", {}) or {}
    if sem.get("main_meaning"):
        lines.append(f"  含义: {sem['main_meaning'][:300]}")
    if sem.get("implied_message"):
        lines.append(f"  暗示: {sem['implied_message'][:200]}")
    if sem.get("text_image_relation"):
        lines.append(f"  图文关系: {sem['text_image_relation'][:150]}")
    if sem.get("meme_or_cultural_reference"):
        lines.append(f"  梗/引用: {sem['meme_or_cultural_reference'][:150]}")
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
            lines.append(f"  语气: {'、'.join(tones[:4])}")
    msg_text = content.get("message_text", "")
    if msg_text:
        lines.append(f"  附带消息: {_sanitize_text(str(msg_text)[:200])}")
    return "\n".join(lines)


@_renderer("read_video")
def _render_read_video(data: dict) -> str:  # noqa: C901
    content = data.get("data", {}) or {}
    lines: list[str] = ["[视频分析]"]
    if content.get("video_type"):
        lines.append(f"  类型: {content['video_type']}")
    if content.get("duration_summary"):
        lines.append(f"  时长: {content['duration_summary'][:60]}")
    if content.get("visual_summary"):
        lines.append(f"  画面: {content['visual_summary'][:300]}")
    if content.get("audio_or_speech_summary"):
        lines.append(f"  音频: {content['audio_or_speech_summary'][:200]}")
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
            lines.append(f"  关键事件: {'; '.join(summaries)}")
    if content.get("semantic_meaning"):
        lines.append(f"  含义: {content['semantic_meaning'][:300]}")
    if content.get("contextual_meaning"):
        lines.append(f"  上下文含义: {content['contextual_meaning'][:200]}")
    if content.get("visible_text"):
        vt = content["visible_text"]
        if isinstance(vt, list):
            vt = " | ".join(str(t) for t in vt)
        lines.append(f"  文字: {str(vt)[:200]}")
    if content.get("confidence"):
        lines.append(f"  置信度: {content['confidence']}")
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
            lines.append(f"  语气: {'、'.join(tones[:4])}")
    msg_text = content.get("message_text", "")
    if msg_text:
        lines.append(f"  附带消息: {_sanitize_text(str(msg_text)[:200])}")
    return "\n".join(lines)
