from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _top(data: dict) -> dict:
    """Normalize to ``{"data": {...}}`` wrapper format.

    Tool renderers expect a ``{"data": {...}}`` envelope. Re-wrap legacy
    payloads that still provide only the inner data dict.
    """
    if "data" not in data:
        return {"data": data}
    return data


def render_system_prompt(settings, *, values: dict[str, str]) -> str:
    template_path = _resolve_template_path(settings.prompt.system_template_path)
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    replacements = {"runtime_identity_block": _build_runtime_identity_block(None)}
    replacements.update(values)
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_model_messages(working_context, settings) -> list[dict[str, str]]:
    system = render_system_prompt(
        settings,
        values={
            "runtime_identity_block": _build_runtime_identity_block(
                working_context.context
            ),
        },
    )
    user = _build_user_content(working_context)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_working_context(working_context) -> str:
    context = working_context.context
    lines = [
        "# Working Context",
        "",
        "## Message To Answer",
        f"- User ID: `{context.user_id}`",
        f"- Content: {_sanitize_text(context.current_message)}",
        "",
        "## Runtime Metadata",
        f"- Chat type: `{context.chat_type}`",
        f"- Chat ID: `{context.chat_id}`",
        f"- Bot self ID: `{context.bot_id or 'unknown'}`",
        f"- Trigger: `{context.trigger_reason}`",
        f"- Parser: `{context.parser_version}`",
        f"- Context: `{context.context_version}`",
        f"- Profile: `{context.profile_version}`",
    ]
    if working_context.evidence:
        lines.extend(["", "## Evidence"])
    for block in working_context.evidence:
        lines.append(
            f"- `{block.kind}` / `{block.label}`: {_sanitize_text(block.content)}"
        )
    return "\n".join(lines)


def _build_runtime_identity_block(context) -> str:
    bot_id = _sanitize_text(str(getattr(context, "bot_id", "") or "unknown"))
    chat_id = _sanitize_text(str(getattr(context, "chat_id", "") or "unknown"))
    user_id = _sanitize_text(str(getattr(context, "user_id", "") or "unknown"))
    return "\n".join(
        [
            "## 运行时身份（动态注入）",
            "",
            f"- 你的 QQ/self_id：`{bot_id}`",
            f"- 当前会话 ID：`{chat_id}`",
            f"- 当前发起用户 ID：`{user_id}`",
        ]
    )


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
    sender = context.current_sender or context.user_id
    parts = [
        "# 本轮回复任务",
        "",
        "## 要回答的用户消息",
        "",
        f"- 发送者：{_sanitize_text(sender)}",
        f"- 用户 ID：`{_sanitize_text(context.user_id)}`",
        f"- 触发原因：`{_sanitize_text(context.trigger_reason)}`",
        "- 消息内容：",
        "",
        f"> {_sanitize_text(context.current_message)}",
        "",
        "## 会话元信息",
        "",
        f"- 会话类型：`{_sanitize_text(context.chat_type)}`",
        f"- 会话 ID：`{_sanitize_text(context.chat_id)}`",
        f"- 机器人 self_id：`{_sanitize_text(context.bot_id or 'unknown')}`",
        f"- 当前时间：`{_sanitize_text(context.current_time or 'unknown')}`",
    ]

    quoted = _render_evidence(working_context, {"track_reply"})
    if quoted:
        parts.extend(["", "## 引用消息", "", quoted])

    recent = _render_evidence(
        working_context,
        {"load_context", "extract_forward", "load_profile"},
        include_errors=True,
    )
    if recent:
        parts.extend(["", "## 相关上下文", "", recent])

    visual = _render_evidence(working_context, {"read_picture", "read_video"})
    if visual:
        parts.extend(["", "## 视觉分析", "", visual])

    reply_instruction = str(getattr(context, "group_instruction", "") or "")
    if not reply_instruction or reply_instruction == "group":
        reply_instruction = (
            (
                "回复要短、快、有判断，适合插入群聊。不要长篇解释；"
                "除非用户明确要求详细分析，否则控制在 1 到 4 句话。"
            )
            if context.chat_type == "group"
            else (
                "回复更完整，但仍然保持直接、有判断、机智。"
                "能给结论就先给结论，必要时再解释。"
            )
        )
    parts.extend(
        [
            "",
            "## 回复要求",
            "",
            f"- {_sanitize_text(reply_instruction)}",
            "- 请生成一条可以直接发送到 IM 平台的回复",
        ]
    )
    return "\n".join(parts)


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
        return f"- **工具错误 `{label}`**：{_sanitize_text(content[:800])}"

    try:
        payload = json.loads(content) if content else {}
    except (json.JSONDecodeError, TypeError):
        return _sanitize_text(content[:2000])

    if not isinstance(payload, dict):
        return _sanitize_text(content[:2000])

    payload = _top(payload)
    failed = _render_failed_tool_response(label, payload)
    if failed:
        return failed
    renderer = _RENDERERS.get(label)
    if renderer:
        return renderer(payload)
    return f"```json\n{_sanitize_text(content[:2000])}\n```"


def _render_failed_tool_response(label: str, payload: dict) -> str:
    if str(payload.get("status", "") or "") != "failed":
        return ""
    error_code = str(payload.get("error_code", "") or "unknown_error")
    message = str(payload.get("message", "") or "工具返回失败")
    retryable = payload.get("retryable", False)
    retry_text = "可重试" if retryable else "不可重试"
    return (
        f"- **工具 `{label}` 失败**：{_sanitize_text(message)} "
        f"(`{error_code}`, {retry_text})"
    )


_RENDERERS: dict[str, Any] = {}


def _renderer(name: str):
    """Decorator to register a renderer for a tool label."""

    def wrapper(fn):
        _RENDERERS[name] = fn
        return fn

    return wrapper


@_renderer("track_reply")
def _render_track_reply(data: dict) -> str:
    status = str(data.get("status", "") or "")
    error_code = str(data.get("error_code", "") or "")
    message = str(data.get("message", "") or "")
    messages = data.get("data", {}).get("messages", []) or []
    if not messages:
        if status == "failed" or error_code:
            detail = message or "引用链为空，不要重复调用 track_reply。"
            return f"- **引用链不可继续查询**：{_sanitize_text(detail)}"
        return "- **引用链为空**：这条链已经查完，不要重复调用 `track_reply`。"
    lines: list[str] = []
    for msg in messages:
        ts = str(msg.get("timestamp", "") or "unknown")
        uid = str(msg.get("user_id", "") or "unknown")
        raw = str(msg.get("raw_message", "") or "")
        lines.append(f"- `{ts}` 用户 `{uid}`：{_sanitize_text(raw)}")
    root = str(data.get("data", {}).get("root_message_id") or "")
    if root:
        lines.append(f"- 根消息 ID：`{root}`")
    return "\n".join(lines)


@_renderer("load_context")
def _render_load_context(data: dict) -> str:
    messages = data.get("data", {}).get("messages", []) or []
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
        for msg in by_date[date_key]:
            ts = str(msg.get("timestamp", "") or "")
            time_part = ts[11:19] if len(ts) >= 19 else ts or "unknown"
            uid = str(msg.get("user_id", "") or "unknown")
            raw = str(msg.get("raw_message", "") or "")
            tags = []
            if bool(msg.get("has_image", False)):
                tags.append("图片")
            if bool(msg.get("has_forward", False)):
                tags.append("转发")
            suffix = f"（{', '.join(tags)}）" if tags else ""
            lines.append(f"- `{time_part}` 用户 `{uid}`：{_sanitize_text(raw)}{suffix}")
    return "\n".join(lines)


@_renderer("extract_forward")
def _render_extract_forward(data: dict) -> str:
    items = data.get("data", {}).get("forward_messages", []) or []
    if not items:
        return "- **合并转发为空**"
    lines: list[str] = ["### 合并转发内容"]
    for item in items:
        nick = str(item.get("nickname", "") or "unknown")
        summary = str(item.get("content_summary", "") or "")
        depth = int(item.get("depth", 0))
        indent = "  " * depth
        lines.append(f"{indent}- **{_sanitize_text(nick)}**：{_sanitize_text(summary)}")
    return "\n".join(lines)


@_renderer("load_profile")
def _render_load_profile(data: dict) -> str:
    profile = data.get("data", {}) or {}
    if not profile:
        return "- **用户档案**：无用户档案，只有空白 ID"
    labels = {
        "username": "昵称",
        "preferred_name": "偏好称呼",
        "group_nickname": "群昵称",
        "group_instruction": "群聊指令",
        "private_instruction": "私聊指令",
        "language_style": "语言风格",
        "habit_preferences": "习惯偏好",
    }
    lines: list[str] = ["### 用户档案"]
    for key, value in profile.items():
        label = labels.get(key, key)
        if isinstance(value, list):
            safe = ", ".join(_sanitize_text(str(v)) for v in value if v)
            if safe:
                lines.append(f"- **{label}**：{safe}")
        elif value:
            lines.append(f"- **{label}**：{_sanitize_text(str(value))}")
    return "\n".join(lines) if len(lines) > 1 else "- **用户档案**：无用户档案"


@_renderer("read_picture")
def _render_read_picture(data: dict) -> str:  # noqa: C901
    content = data.get("data", {}) or {}
    lines: list[str] = ["### 图片分析"]
    if content.get("image_type"):
        lines.append(f"- **类型**：{_sanitize_text(str(content['image_type']))}")
    if content.get("confidence"):
        lines.append(f"- **置信度**：{_sanitize_text(str(content['confidence']))}")
    lit = content.get("literal_content", {}) or {}
    if lit.get("summary"):
        lines.append(f"- **概述**：{_sanitize_text(str(lit['summary'])[:300])}")
    if lit.get("scene"):
        lines.append(f"- **场景**：{_sanitize_text(str(lit['scene'])[:120])}")
    if lit.get("visible_objects"):
        objs = lit["visible_objects"]
        if isinstance(objs, list):
            objs = "、".join(str(o) for o in objs)
        lines.append(f"- **物品**：{_sanitize_text(str(objs)[:200])}")
    if lit.get("visible_people"):
        people = lit["visible_people"]
        if isinstance(people, list):
            people = "、".join(str(p) for p in people)
        lines.append(f"- **人物**：{_sanitize_text(str(people)[:200])}")
    if lit.get("ocr_text"):
        ocr = lit["ocr_text"]
        if isinstance(ocr, list):
            ocr = " | ".join(str(t) for t in ocr)
        lines.append(f"- **文字**：{_sanitize_text(str(ocr)[:300])}")
    sem = content.get("semantic_interpretation", {}) or {}
    if sem.get("main_meaning"):
        lines.append(f"- **含义**：{_sanitize_text(str(sem['main_meaning'])[:300])}")
    if sem.get("implied_message"):
        lines.append(f"- **暗示**：{_sanitize_text(str(sem['implied_message'])[:200])}")
    if sem.get("text_image_relation"):
        lines.append(
            f"- **图文关系**：{_sanitize_text(str(sem['text_image_relation'])[:150])}"
        )
    if sem.get("meme_or_cultural_reference"):
        meme = _sanitize_text(str(sem["meme_or_cultural_reference"])[:150])
        lines.append(f"- **梗/引用**：{meme}")
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
        lines.append(f"- **附带消息**：{_sanitize_text(str(msg_text)[:200])}")
    return "\n".join(lines)


@_renderer("read_video")
def _render_read_video(data: dict) -> str:  # noqa: C901
    content = data.get("data", {}) or {}
    lines: list[str] = ["### 视频分析"]
    if content.get("video_type"):
        lines.append(f"- **类型**：{_sanitize_text(str(content['video_type']))}")
    if content.get("duration_summary"):
        lines.append(
            f"- **时长**：{_sanitize_text(str(content['duration_summary'])[:60])}"
        )
    if content.get("visual_summary"):
        lines.append(
            f"- **画面**：{_sanitize_text(str(content['visual_summary'])[:300])}"
        )
    if content.get("audio_or_speech_summary"):
        audio = _sanitize_text(str(content["audio_or_speech_summary"])[:200])
        lines.append(f"- **音频**：{audio}")
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
            lines.append(f"- **关键事件**：{_sanitize_text('; '.join(summaries))}")
    if content.get("semantic_meaning"):
        lines.append(
            f"- **含义**：{_sanitize_text(str(content['semantic_meaning'])[:300])}"
        )
    if content.get("contextual_meaning"):
        contextual_meaning = _sanitize_text(str(content["contextual_meaning"])[:200])
        lines.append(f"- **上下文含义**：{contextual_meaning}")
    if content.get("visible_text"):
        vt = content["visible_text"]
        if isinstance(vt, list):
            vt = " | ".join(str(t) for t in vt)
        lines.append(f"- **文字**：{_sanitize_text(str(vt)[:200])}")
    if content.get("confidence"):
        lines.append(f"- **置信度**：{_sanitize_text(str(content['confidence']))}")
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
        lines.append(f"- **附带消息**：{_sanitize_text(str(msg_text)[:200])}")
    return "\n".join(lines)
