"""Escalation: re-analyze a low-confidence image with a stronger model.

Uses the upgrade prompts from docs/dev/vision.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from .prompts import VISUAL_JSON_SCHEMA
from .router import build_escalation_requirement, select_escalation_model
from .schemas import VisualAnalysis, analysis_to_dict, normalize_analysis

logger = logging.getLogger("qq_grok_reply.vision.escalator")

ESCALATION_UPGRADE_TEMPLATE = """---

当前任务是一次"升级复核"而不是普通图片初读。

你将收到：
1. 原始图片；
2. 可选聊天上下文；
3. 初步解析结果；
4. 本次要求。

请以原始图片与上下文为最高依据，参考但不要盲从初步解析结果。

你的目标是：
- 修正初步解析中的遗漏、误判或过度推测；
- 补充更精确的图文含义、语义解释、情绪语气线索；
- 保持输出 JSON 结构与通用 schema 完全一致；
- 不要输出 diff，不要评价低成本模型，不要解释升级原因；
- 不要增删任何字段。

如果初步解析正确，可以保留其判断；如果发现错误，直接在最终 JSON 中给出修正后的结果。
"""

ESCALATION_INPUT_TEMPLATE = """要求：
{requirement}

聊天上下文：
{chat_context}

初步解析：
{flash_result_json}

请基于原始图片和以上信息，输出修正后的最终 JSON。"""


async def escalate_analysis(
    client,
    image_base64: str,
    initial: VisualAnalysis,
    intent: str,
    chat_context: str,
    settings,
    *,
    model_override: str | None = None,
    image_mime_type: str = "image/png",
) -> VisualAnalysis:
    """Run an escalation analysis using a stronger model.

    Args:
        client: DashScope OpenAI-compatible client.
        image_base64: Base64-encoded image data.
        initial: The initial (flash) analysis — provides context.
        intent: The detected user intent.
        chat_context: Lightweight text context.
        settings: Plugin settings.

    Returns:
        The escalated (potentially improved) analysis, or the original
        analysis if escalation failed.
    """
    model = model_override or select_escalation_model(initial, intent, settings)
    if model is None:
        logger.debug("escalation: no suitable model found, keeping initial")
        return initial

    requirement = build_escalation_requirement(initial, intent, settings)
    flash_json = initial.raw_model_output.strip() or json.dumps(
        analysis_to_dict(initial), ensure_ascii=False
    )

    # Build escalation system prompt
    system_prompt = ESCALATION_UPGRADE_TEMPLATE
    schema_part = f"\n\n输出必须严格符合以下 JSON 结构：\n\n{VISUAL_JSON_SCHEMA}"
    system_prompt += schema_part

    # Build user message with requirement + flash result
    input_text = ESCALATION_INPUT_TEMPLATE.format(
        requirement=requirement,
        chat_context=chat_context or "（无上下文）",
        flash_result_json=flash_json or "（无初步解析）",
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": input_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_mime_type};base64,{image_base64}"
                    },
                },
            ],
        },
    ]

    temperature = settings.vision.temperature
    timeout = settings.vision.timeout_sec

    start = datetime.now()
    try:

        def _call():
            return client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=timeout,
            )

        completion = await asyncio.to_thread(_call)
    except Exception as exc:
        elapsed = (datetime.now() - start).total_seconds()
        logger.warning(
            "escalation: model call failed model=%s elapsed=%.1fs error=%s",
            model,
            elapsed,
            exc,
        )
        return initial

    raw_content = _extract_content(completion)
    if not raw_content:
        logger.warning("escalation: empty response from model=%s", model)
        return initial

    try:
        data = json.loads(raw_content)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning("escalation: invalid JSON from model=%s error=%s", model, exc)
        return initial

    if not isinstance(data, dict):
        return initial

    escalated = normalize_analysis(data, raw_model_output=raw_content)
    elapsed = (datetime.now() - start).total_seconds()
    logger.info(
        "escalation: success model=%s old_conf=%.2f new_conf=%.2f elapsed=%.1fs",
        model,
        initial.confidence,
        escalated.confidence,
        elapsed,
    )
    return escalated


def _extract_content(completion) -> str:
    try:
        choices = completion.choices
        if choices:
            content = choices[0].message.content
            if content is not None:
                return str(content)
    except AttributeError:
        pass
    return ""
