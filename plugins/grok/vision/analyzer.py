from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from openai import APIConnectionError, APIStatusError, APITimeoutError

from .prompts import build_vision_messages
from .schemas import VisualAnalysis, normalize_analysis

if TYPE_CHECKING:
    from openai import OpenAI

logger = logging.getLogger("grok.vision.analyzer")


async def analyze_image(
    client: OpenAI,
    image_base64: str,
    file_unique: str,
    settings,
    *,
    chat_context: str = "",
    model_override: str | None = None,
    image_mime_type: str = "image/png",
) -> VisualAnalysis:
    model = model_override or settings.vision.image_fast_model
    temperature = settings.vision.temperature
    timeout = settings.vision.timeout_sec

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    messages = build_vision_messages(
        chat_context=chat_context,
        current_time=current_time,
    )
    user_msg = messages[1]
    assert isinstance(user_msg["content"], list)
    user_msg["content"].append(
        {
            "type": "image_url",
            "image_url": {"url": f"data:{image_mime_type};base64,{image_base64}"},
        }
    )

    start = datetime.now()
    try:
        completion = await _call_vision_model(
            client, model, messages, temperature, timeout
        )
    except APITimeoutError as exc:
        elapsed = (datetime.now() - start).total_seconds()
        logger.warning(
            "vision: timeout file_unique=%s model=%s elapsed=%.1fs error=%s",
            file_unique,
            model,
            elapsed,
            exc,
        )
        return VisualAnalysis(error_code="vision_timeout")
    except APIConnectionError as exc:
        elapsed = (datetime.now() - start).total_seconds()
        logger.warning(
            "vision: connection error file_unique=%s model=%s elapsed=%.1fs error=%s",
            file_unique,
            model,
            elapsed,
            exc,
        )
        return VisualAnalysis(error_code="vision_connection_error")
    except APIStatusError as exc:
        elapsed = (datetime.now() - start).total_seconds()
        logger.warning(
            "vision: api status error file_unique=%s model=%s status=%s elapsed=%.1fs",
            file_unique,
            model,
            exc.status_code,
            elapsed,
        )
        return VisualAnalysis(error_code="vision_api_error")
    except Exception as exc:
        elapsed = (datetime.now() - start).total_seconds()
        logger.warning(
            "vision: model call failed file_unique=%s model=%s elapsed=%.1fs error=%s",
            file_unique,
            model,
            elapsed,
            exc,
        )
        return VisualAnalysis(error_code="vision_llm_error")

    raw_content = _extract_content(completion)
    if not raw_content:
        return VisualAnalysis(error_code="vision_empty_response")

    try:
        data = json.loads(raw_content)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            "vision: invalid JSON from model file_unique=%s error=%s",
            file_unique,
            exc,
        )
        return VisualAnalysis(
            error_code="vision_invalid_json",
            raw_model_output=raw_content,
        )

    if not isinstance(data, dict):
        return VisualAnalysis(
            error_code="vision_invalid_json",
            raw_model_output=raw_content,
        )

    analysis = normalize_analysis(data, raw_model_output=raw_content)
    if not analysis.error_code:
        elapsed = (datetime.now() - start).total_seconds()
        logger.info(
            "vision: success file_unique=%s model=%s confidence=%.2f elapsed=%.1fs",
            file_unique,
            model,
            analysis.confidence,
            elapsed,
        )
    return analysis


async def _call_vision_model(
    client,
    model: str,
    messages: list,
    temperature: float,
    timeout: int,
):
    def _sync_call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
            timeout=timeout,
        )

    return await asyncio.to_thread(_sync_call)


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
