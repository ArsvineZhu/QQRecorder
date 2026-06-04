from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

logger = logging.getLogger("grok.vision.schemas")

MAX_VISUAL_CONTEXT_CHARS = 1200

DISCARD_DECISION_FIELDS = frozenset(
    {
        "should_reply",
        "reply_style",
        "memory_write",
        "response_policy",
        "suggested_response",
    }
)


@dataclass
class LiteralContent:
    summary: str = ""
    visible_objects: list[str] = field(default_factory=list)
    visible_people: list[str] = field(default_factory=list)
    scene: str = ""
    ocr_text: list[str] = field(default_factory=list)


@dataclass
class SemanticInterpretation:
    main_meaning: str = ""
    implied_message: str = ""
    meme_or_cultural_reference: str = ""
    text_image_relation: str = ""


@dataclass
class ToneItem:
    label: str = ""
    intensity: float = 0.0


@dataclass
class AffectiveReading:
    tone: list[ToneItem] = field(default_factory=list)
    evidence: str = ""


@dataclass
class ContextDependency:
    requires_context: bool = False
    used_context: str = ""
    meaning_without_context: str = ""
    meaning_with_context: str = ""


@dataclass
class Uncertainty:
    ambiguous_points: list[str] = field(default_factory=list)
    possible_alternative_meanings: list[str] = field(default_factory=list)


@dataclass
class SafetyAndPrivacy:
    contains_face: bool = False
    contains_personal_info: bool = False
    contains_qr_or_barcode: bool = False
    contains_sensitive_document: bool = False


@dataclass
class VisualAnalysis:
    """Structured analysis result from vision model, mirroring visual_semantic_json."""

    image_type: str = ""
    literal_content: LiteralContent = field(default_factory=LiteralContent)
    semantic_interpretation: SemanticInterpretation = field(
        default_factory=SemanticInterpretation
    )
    confidence: float = 0.0
    affective_reading: AffectiveReading = field(default_factory=AffectiveReading)
    context_dependency: ContextDependency = field(default_factory=ContextDependency)
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    safety_and_privacy: SafetyAndPrivacy = field(default_factory=SafetyAndPrivacy)

    # Non-JSON fields
    error_code: str = ""
    raw_model_output: str = ""


def analysis_to_dict(analysis: VisualAnalysis) -> dict[str, Any]:
    """Convert a VisualAnalysis tree to JSON-safe dict form."""
    raw = _convert_dataclass(analysis)
    raw.pop("error_code", None)
    raw.pop("raw_model_output", None)
    return raw


def normalize_analysis(
    raw: dict[str, Any],
    raw_model_output: str = "",
) -> VisualAnalysis:
    """Parse and normalize a raw dict from a vision model JSON response.

    Fills missing fields with defaults, clamps numeric values,
    discards decision/response fields, and logs warnings for anomalies.
    """
    lit = raw.get("literal_content", {}) or {}
    sem = raw.get("semantic_interpretation", {}) or {}
    aff = raw.get("affective_reading", {}) or {}
    ctx = raw.get("context_dependency", {}) or {}
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

    analysis = VisualAnalysis(
        image_type=str(raw.get("image_type", "") or ""),
        literal_content=LiteralContent(
            summary=str(lit.get("summary", "") or ""),
            visible_objects=_coerce_string_list(lit.get("visible_objects", [])),
            visible_people=_coerce_string_list(lit.get("visible_people", [])),
            scene=str(lit.get("scene", "") or ""),
            ocr_text=_coerce_string_list(lit.get("ocr_text", [])),
        ),
        semantic_interpretation=SemanticInterpretation(
            main_meaning=str(sem.get("main_meaning", "") or ""),
            implied_message=str(sem.get("implied_message", "") or ""),
            meme_or_cultural_reference=str(
                sem.get("meme_or_cultural_reference", "") or ""
            ),
            text_image_relation=str(sem.get("text_image_relation", "") or ""),
        ),
        confidence=_clamp_float(raw.get("confidence", 0.0)),
        affective_reading=AffectiveReading(
            tone=tone_list,
            evidence=str(aff.get("evidence", "") or ""),
        ),
        context_dependency=ContextDependency(
            requires_context=bool(ctx.get("requires_context", False)),
            used_context=str(ctx.get("used_context", "") or ""),
            meaning_without_context=str(ctx.get("meaning_without_context", "") or ""),
            meaning_with_context=str(ctx.get("meaning_with_context", "") or ""),
        ),
        uncertainty=Uncertainty(
            ambiguous_points=_coerce_string_list(unc.get("ambiguous_points", [])),
            possible_alternative_meanings=_coerce_string_list(
                unc.get("possible_alternative_meanings", [])
            ),
        ),
        safety_and_privacy=SafetyAndPrivacy(
            contains_face=bool(saf.get("contains_face", False)),
            contains_personal_info=bool(saf.get("contains_personal_info", False)),
            contains_qr_or_barcode=bool(saf.get("contains_qr_or_barcode", False)),
            contains_sensitive_document=bool(
                saf.get("contains_sensitive_document", False)
            ),
        ),
        raw_model_output=raw_model_output,
    )

    # Log decision fields that were discarded
    discarded = DISCARD_DECISION_FIELDS & raw.keys()
    if discarded:
        logger.debug("vision: discarded decision fields %s", discarded)

    return analysis


def render_visual_context(analysis: VisualAnalysis) -> str:
    """Render a VisualAnalysis into a structured, budget-bounded block."""
    lines = [f"图片类型：{analysis.image_type or '图片'}"]
    if analysis.confidence > 0:
        lines.append(f"置信度：{analysis.confidence:.2f}")

    _append_field(lines, "画面概述", analysis.literal_content.summary, 180)
    _append_field(lines, "场景", analysis.literal_content.scene, 80)
    _append_field(
        lines,
        "可见对象",
        _join_items(
            analysis.literal_content.visible_objects,
            item_limit=5,
            char_limit=120,
        ),
    )
    _append_field(
        lines,
        "画面人物",
        _join_items(
            analysis.literal_content.visible_people,
            item_limit=4,
            char_limit=80,
        ),
    )
    _append_field(
        lines,
        "识别文字",
        _join_items(analysis.literal_content.ocr_text, item_limit=6, char_limit=180),
    )
    _append_field(
        lines,
        "图文关系",
        analysis.semantic_interpretation.text_image_relation,
        120,
    )
    _append_field(
        lines,
        "核心含义",
        analysis.semantic_interpretation.main_meaning,
        140,
    )
    _append_field(
        lines,
        "隐含信息",
        analysis.semantic_interpretation.implied_message,
        120,
    )
    _append_field(
        lines,
        "梗/文化引用",
        analysis.semantic_interpretation.meme_or_cultural_reference,
        100,
    )

    if analysis.context_dependency.requires_context:
        detail = "需要结合聊天上下文"
        if analysis.context_dependency.used_context:
            detail += "；已使用：" + _truncate_text(
                analysis.context_dependency.used_context,
                80,
            )
        lines.append(f"上下文依赖：{detail}")
    _append_field(
        lines,
        "脱离上下文",
        analysis.context_dependency.meaning_without_context,
        100,
    )
    _append_field(
        lines,
        "结合上下文",
        analysis.context_dependency.meaning_with_context,
        120,
    )

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

    safety_notes = _render_safety_notes(analysis.safety_and_privacy)
    if safety_notes:
        lines.append(f"隐私/安全：{safety_notes}")

    return _finalize_rendered_block(
        lines,
        footer="说明：以上为自动视觉分析，可能存在误判",
        max_chars=MAX_VISUAL_CONTEXT_CHARS,
    )


def _clamp_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


def _convert_dataclass(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _convert_dataclass(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, list):
        return [_convert_dataclass(item) for item in value]
    return value


def _append_field(
    lines: list[str],
    label: str,
    value: str,
    max_value_chars: int | None = None,
) -> None:
    normalized = value.strip()
    if not normalized:
        return
    if max_value_chars is not None:
        normalized = _truncate_text(normalized, max_value_chars)
    lines.append(f"{label}：{normalized}")


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


def _join_items(values: list[str], *, item_limit: int, char_limit: int) -> str:
    items = [item.strip() for item in values if item and item.strip()]
    if not items:
        return ""
    joined = "、".join(items[:item_limit])
    if len(items) > item_limit:
        joined += f" 等 {len(items)} 项"
    return _truncate_text(joined, char_limit)


def _render_safety_notes(safety: SafetyAndPrivacy) -> str:
    flags: list[str] = []
    if safety.contains_face:
        flags.append("含人脸")
    if safety.contains_personal_info:
        flags.append("含个人信息")
    if safety.contains_qr_or_barcode:
        flags.append("含二维码或条码")
    if safety.contains_sensitive_document:
        flags.append("可能是敏感文档")
    return "、".join(flags)


def _finalize_rendered_block(
    lines: list[str],
    *,
    footer: str,
    max_chars: int,
) -> str:
    content_lines = [line for line in lines if line.strip()]
    if not content_lines:
        return footer

    body = "\n".join(content_lines)
    if len(body) + 1 + len(footer) <= max_chars:
        return f"{body}\n{footer}"

    allowed_body = max_chars - len(footer) - 1
    if allowed_body <= 1:
        return _truncate_text(footer, max_chars)

    trimmed_body = _truncate_text(body, allowed_body)
    return f"{trimmed_body}\n{footer}"
