"""Multi-model router for image analysis.

Implements the full decision tree from docs/dev/vision.md:

1. Size-based: > 50MB → skip
2. Intent-based: detail request → detail model; semantic request → semantic model
3. Default: fast model (flash)
4. After flash: escalation if low confidence
"""

from __future__ import annotations

import re

from ..config_schema import ReplyPluginSettings

# Keywords for intent detection
_DETAIL_KEYWORDS = re.compile(
    r"(定位|小字|坐标|细节|看清楚|按钮|在哪|报错|界面|截图|找)"
    r"|(找一下|看看.*哪里|什么位置|哪里.*有|看不清楚|写的什么)"
    r"|(detail|location|button|position|find|look\s+at)",
    re.IGNORECASE,
)

_SEMANTIC_KEYWORDS = re.compile(
    r"(什么意思|仔细解读|表达啥|结合上下文|梗|这个图|他发这个)"
    r"|(什么含义|什么梗|想表达|情绪|语气|好笑在哪)"
    r"|(meaning|meme|context|interpret|understand|joke)",
    re.IGNORECASE,
)


def detect_image_intent(
    message_text: str,
    settings: ReplyPluginSettings,
) -> str:
    """Detect user intent for the given image message.

    Returns:
        "detail" — user asks about location/small-text/screenshot details
        "semantic" — user asks about meaning/meme/context interpretation
        "default" — no special intent detected
    """
    if not message_text:
        return "default"

    has_detail = bool(_DETAIL_KEYWORDS.search(message_text))
    has_semantic = bool(_SEMANTIC_KEYWORDS.search(message_text))

    if has_detail and has_semantic:
        # Both: prefer semantic if the message is longer on semantic keywords
        detail_matches = len(_DETAIL_KEYWORDS.findall(message_text))
        semantic_matches = len(_SEMANTIC_KEYWORDS.findall(message_text))
        return "semantic" if semantic_matches > detail_matches else "detail"

    if has_detail:
        return "detail"
    if has_semantic:
        return "semantic"
    return "default"


def select_model(
    intent: str,
    image_bytes_size: int,
    image_type: str,
    settings: ReplyPluginSettings,
) -> str:
    """Select the vision model based on intent, image size, and type.

    Implements the routing decision tree:
    - size > 50MB → skip (caller handles)
    - detail intent + size >= 1MB → detail_model
    - detail intent + size < 1MB → fast_model
    - semantic intent + size >= 1MB → deep_semantic_model
    - semantic intent + size < 1MB → fast_model
    - default → fast_model
    """
    vision = settings.vision
    threshold = vision.router_image_bytes_threshold  # default 1MB

    if intent == "detail":
        if image_bytes_size >= threshold:
            return vision.image_detail_model  # qwen3-vl-plus
        return vision.image_fast_model

    if intent == "semantic":
        if image_bytes_size >= threshold:
            return vision.image_deep_semantic_model  # qwen3.7-plus
        return vision.image_fast_model

    # default
    return vision.image_fast_model


def needs_escalation(
    analysis,
    intent: str,
    image_bytes_size: int,
    settings: ReplyPluginSettings,
) -> bool:
    """Determine if the initial flash analysis should be escalated.

    Returns:
        True if escalation should run.
    """
    vision = settings.vision
    if not vision.escalation_enabled:
        return False

    if analysis.error_code:
        # If the flash call itself failed, don't waste tokens escalating
        return False

    if analysis.confidence >= vision.escalation_min_confidence:
        return False

    # Check if image size allows escalation (full-quality image still available)
    if image_bytes_size > vision.api_image_bytes_max:
        return False

    return True


def select_escalation_model(
    analysis,
    intent: str,
    settings: ReplyPluginSettings,
) -> str | None:
    """Select which model to escalate to.

    Returns:
        Model name, or None if escalation is not applicable.
    """
    vision = settings.vision
    image_type = analysis.image_type or ""

    # If intent is already semantic or detail, escalate to the respective model
    if intent == "semantic":
        return vision.image_deep_semantic_model
    if intent == "detail":
        return vision.image_detail_model

    # Default: route based on image characteristics
    if image_type in settings.vision.escalation_detail_screenshot_types:
        return vision.image_detail_model

    # Fall back to semantic model
    return vision.image_deep_semantic_model


def build_escalation_requirement(
    analysis,
    intent: str,
    settings: ReplyPluginSettings,
) -> str:
    """Build the escalation requirement prompt fragment based on the
    initial analysis results and user intent."""
    image_type = analysis.image_type or ""

    if intent == "detail" or image_type in ("screenshot", "document"):
        return (
            "本次升级重点是“视觉细节复核”，不是深度聊天语义解释。\n\n"
            "请重点优化以下内容：\n"
            "- `literal_content.*`\n"
            "- `semantic_interpretation.text_image_relation`\n"
            "- `uncertainty.ambiguous_points`\n"
            "- `safety_and_privacy`\n\n"
            "请特别注意：\n"
            "1. 识别图片中的小字、截图文字、按钮文字、错误提示、弹窗内容；\n"
            "2. 识别重要物体、符号、界面元素、角色、动物、道具、图标；\n"
            "3. 对画面中关键元素给出相对位置描述。\n"
        )

    return (
        "本次升级重点是“深度语义解释”，不是视觉定位，也不是细节检测。\n\n"
        "请重点优化以下字段：\n"
        "- `semantic_interpretation.*`\n"
        "- `affective_reading`\n"
        "- `context_dependency`\n"
        "- `uncertainty.possible_alternative_meanings`\n\n"
        "判断图片含义时，请区分三层：\n"
        "1. 画面字面内容：图中直接可见的角色、动作、表情、文字；\n"
        "2. 图片自身语义：只看这张图通常表达什么；\n"
        "3. 上下文语义：结合聊天上下文后，它在当前对话里可能表达什么。\n\n"
        "不要为了显得聪明而过度解读。\n"
    )
