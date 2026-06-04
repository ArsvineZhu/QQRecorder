"""Video analysis schemas — mirrors video_semantic_json from docs/dev/vision.md."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

from .schemas import (
    MAX_VISUAL_CONTEXT_CHARS,
    ToneItem,
    _append_field,
    _clamp_float,
    _coerce_string_list,
    _finalize_rendered_block,
    _join_items,
    _truncate_text,
)

logger = logging.getLogger("qq_grok_reply.vision.video_schemas")


@dataclass
class KeyEvent:
    time_range: str = ""
    event: str = ""


@dataclass
class VideoAffectiveReading:
    tone: list[ToneItem] = field(default_factory=list)
    evidence: str = ""


@dataclass
class VideoUncertainty:
    ambiguous_points: list[str] = field(default_factory=list)
    possible_alternative_meanings: list[str] = field(default_factory=list)


@dataclass
class VideoSafetyAndPrivacy:
    contains_real_person_face: bool = False
    contains_personal_info: bool = False
    contains_qr_or_barcode: bool = False
    contains_sensitive_document: bool = False


@dataclass
class VideoAnalysis:
    """Structured analysis result from video model, mirroring video_semantic_json."""

    media_type: str = "video"
    video_type: str = "unknown"
    duration_summary: str = ""
    visual_summary: str = ""
    key_events: list[KeyEvent] = field(default_factory=list)
    visible_text: list[str] = field(default_factory=list)
    audio_or_speech_summary: str = ""
    semantic_meaning: str = ""
    contextual_meaning: str = ""
    affective_reading: VideoAffectiveReading = field(
        default_factory=VideoAffectiveReading
    )
    uncertainty: VideoUncertainty = field(default_factory=VideoUncertainty)
    safety_and_privacy: VideoSafetyAndPrivacy = field(
        default_factory=VideoSafetyAndPrivacy
    )
    confidence: float = 0.0

    # Non-JSON fields
    error_code: str = ""
    raw_model_output: str = ""


def video_analysis_to_dict(analysis: VideoAnalysis) -> dict[str, Any]:
    """Convert a VideoAnalysis tree to JSON-safe dict form."""
    raw = _convert_dataclass(analysis)
    raw.pop("error_code", None)
    raw.pop("raw_model_output", None)
    return raw


DISCARD_VIDEO_DECISION_FIELDS = frozenset(
    {
        "should_reply",
        "reply_style",
        "memory_write",
        "response_policy",
        "suggested_response",
    }
)


def normalize_video_analysis(
    raw: dict[str, Any],
    raw_model_output: str = "",
) -> VideoAnalysis:
    """Parse and normalize a raw dict from a video model JSON response."""
    aff = raw.get("affective_reading", {}) or {}
    unc = raw.get("uncertainty", {}) or {}
    saf = raw.get("safety_and_privacy", {}) or {}

    tone_list: list[ToneItem] = []
    for item in aff.get("tone", []) or []:
        if isinstance(item, dict):
            tone_list.append(
                ToneItem(
                    label=str(item.get("label", "") or ""),
                    intensity=_clamp_float(item.get("intensity", 0.0)),
                )
            )

    events = []
    for item in raw.get("key_events", []) or []:
        if isinstance(item, dict):
            events.append(
                KeyEvent(
                    time_range=str(item.get("time_range", "") or ""),
                    event=str(item.get("event", "") or ""),
                )
            )

    analysis = VideoAnalysis(
        media_type="video",
        video_type=str(raw.get("video_type", "unknown") or "unknown"),
        duration_summary=str(raw.get("duration_summary", "") or ""),
        visual_summary=str(raw.get("visual_summary", "") or ""),
        key_events=events,
        visible_text=_coerce_string_list(raw.get("visible_text", [])),
        audio_or_speech_summary=str(raw.get("audio_or_speech_summary", "") or ""),
        semantic_meaning=str(raw.get("semantic_meaning", "") or ""),
        contextual_meaning=str(raw.get("contextual_meaning", "") or ""),
        affective_reading=VideoAffectiveReading(
            tone=tone_list,
            evidence=str(aff.get("evidence", "") or ""),
        ),
        uncertainty=VideoUncertainty(
            ambiguous_points=_coerce_string_list(unc.get("ambiguous_points", [])),
            possible_alternative_meanings=_coerce_string_list(
                unc.get("possible_alternative_meanings", [])
            ),
        ),
        safety_and_privacy=VideoSafetyAndPrivacy(
            contains_real_person_face=bool(saf.get("contains_real_person_face", False)),
            contains_personal_info=bool(saf.get("contains_personal_info", False)),
            contains_qr_or_barcode=bool(saf.get("contains_qr_or_barcode", False)),
            contains_sensitive_document=bool(
                saf.get("contains_sensitive_document", False)
            ),
        ),
        confidence=_clamp_float(raw.get("confidence", 0.0)),
        raw_model_output=raw_model_output,
    )

    discarded = DISCARD_VIDEO_DECISION_FIELDS & raw.keys()
    if discarded:
        logger.debug("video: discarded decision fields %s", discarded)

    return analysis


def render_video_context(analysis: VideoAnalysis) -> str:
    """Render a VideoAnalysis into a structured, budget-bounded block."""
    lines = [f"视频类型：{analysis.video_type or '视频'}"]
    if analysis.confidence > 0:
        lines.append(f"置信度：{analysis.confidence:.2f}")

    _append_field(lines, "时长", analysis.duration_summary, 60)
    _append_field(lines, "画面概述", analysis.visual_summary, 180)

    event_summary = _summarize_key_events(analysis.key_events)
    if event_summary:
        lines.append(f"关键事件：{event_summary}")

    _append_field(
        lines,
        "识别文字",
        _join_items(analysis.visible_text, item_limit=6, char_limit=180),
    )
    _append_field(lines, "音频/语音", analysis.audio_or_speech_summary, 140)
    _append_field(lines, "核心含义", analysis.semantic_meaning, 140)
    _append_field(lines, "结合上下文", analysis.contextual_meaning, 140)

    tones = sorted(
        [t for t in analysis.affective_reading.tone if t.intensity > 0],
        key=lambda t: t.intensity,
        reverse=True,
    )
    if tones:
        tone_str = "、".join(f"{t.label}({t.intensity:.1f})" for t in tones[:3])
        lines.append(f"语气倾向：{tone_str}")
    _append_field(lines, "判断依据", analysis.affective_reading.evidence, 100)
    _append_field(
        lines,
        "歧义点",
        _join_items(
            analysis.uncertainty.ambiguous_points,
            item_limit=3,
            char_limit=100,
        ),
    )
    _append_field(
        lines,
        "备选解释",
        _join_items(
            analysis.uncertainty.possible_alternative_meanings,
            item_limit=3,
            char_limit=100,
        ),
    )

    safety_notes = _render_video_safety_notes(analysis.safety_and_privacy)
    if safety_notes:
        lines.append(f"隐私/安全：{safety_notes}")

    return _finalize_rendered_block(
        lines,
        footer="说明：以上为自动视频分析，可能存在误判",
        max_chars=MAX_VISUAL_CONTEXT_CHARS,
    )


def _convert_dataclass(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _convert_dataclass(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, list):
        return [_convert_dataclass(item) for item in value]
    return value


def _summarize_key_events(events: list[KeyEvent]) -> str:
    if not events:
        return ""
    summarized = []
    for item in events[:3]:
        if item.time_range and item.event:
            summarized.append(f"{item.time_range} {item.event}")
        elif item.event:
            summarized.append(item.event)
        elif item.time_range:
            summarized.append(item.time_range)
    if len(events) > 3:
        summarized.append(f"其余 {len(events) - 3} 段")
    return _truncate_text("；".join(summarized), 200)


def _render_video_safety_notes(safety: VideoSafetyAndPrivacy) -> str:
    flags: list[str] = []
    if safety.contains_real_person_face:
        flags.append("含真实人脸")
    if safety.contains_personal_info:
        flags.append("含个人信息")
    if safety.contains_qr_or_barcode:
        flags.append("含二维码或条码")
    if safety.contains_sensitive_document:
        flags.append("可能是敏感文档")
    return "、".join(flags)
