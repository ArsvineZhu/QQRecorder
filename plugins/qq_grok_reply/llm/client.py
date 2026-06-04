import asyncio
import json
from dataclasses import dataclass
from typing import Any

from ..context.types import BuiltContext
from .prompt import build_prompt_messages

TOOL_NAME = "request_more_context"

REQUEST_MORE_CONTEXT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "当局部上下文不足以可靠回答时，申请更大范围的话题上下文。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "为什么当前局部上下文不足，简短说明缺口。",
                }
            },
            "required": ["reason"],
        },
    },
}


class ReplyModelError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class ReplyGenerationResult:
    text: str
    requested_more_context: bool = False
    request_reason: str = ""
    model_name: str = ""
    model_request_summary: str = ""
    model_request_user_prompt: str = ""
    model_response_summary: str = ""


async def generate_reply(
    api, ctx: BuiltContext, settings, *, allow_more_context: bool = True
) -> ReplyGenerationResult:
    messages = build_prompt_messages(ctx, allow_more_context=allow_more_context)
    retries = max(0, settings.model.retries)
    max_tokens = (
        settings.model.max_tokens_group
        if ctx.chat_type == "group" or ctx.variant.startswith("group")
        else settings.model.max_tokens_private
    )
    preview_chars = settings.trace.preview_chars
    user_prompt = str(messages[-1]["content"])
    last_error: Exception | None = None

    for _attempt in range(retries + 1):
        try:
            async with asyncio.timeout(settings.model.timeout_sec):
                response = await _call_chat(
                    api,
                    messages,
                    model=settings.model.model or None,
                    temperature=settings.model.temperature,
                    max_tokens=max_tokens,
                    allow_more_context=allow_more_context,
                )
            request_reason = (
                _extract_more_context_request(response) if allow_more_context else None
            )
            if request_reason:
                return ReplyGenerationResult(
                    text="",
                    requested_more_context=True,
                    request_reason=request_reason,
                    model_name=str(
                        getattr(response, "model", None) or settings.model.model or ""
                    ),
                    model_request_summary=_summarize(
                        messages[-1]["content"], preview_chars
                    ),
                    model_request_user_prompt=user_prompt,
                    model_response_summary=_summarize(
                        f"[request_more_context] {request_reason}",
                        preview_chars,
                    ),
                )
            text = _extract_text(response).strip()
            if not text:
                finish_reason = _safe_finish_reason(response)
                raise ReplyModelError(
                    "empty_response",
                    f"model returned empty content (finish_reason={finish_reason})",
                )
            return ReplyGenerationResult(
                text=text,
                model_name=str(
                    getattr(response, "model", None) or settings.model.model or ""
                ),
                model_request_summary=_summarize(
                    messages[-1]["content"], preview_chars
                ),
                model_request_user_prompt=user_prompt,
                model_response_summary=_summarize(text, preview_chars),
            )
        except ReplyModelError:
            raise
        except TimeoutError as exc:
            raise ReplyModelError("llm_timeout", "model request timed out") from exc
        except Exception as exc:
            last_error = exc
    raise ReplyModelError("llm_error", str(last_error or "unknown model error"))


async def _call_chat(
    api,
    messages: list[dict[str, str]],
    *,
    model: str | None,
    temperature: float,
    max_tokens: int,
    allow_more_context: bool,
):
    common_kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not allow_more_context:
        return await api.ai.chat(messages, **common_kwargs)
    try:
        return await api.ai.chat(
            messages,
            **common_kwargs,
            tools=[REQUEST_MORE_CONTEXT_TOOL],
        )
    except TypeError:
        return await api.ai.chat(
            messages,
            **common_kwargs,
            functions=[REQUEST_MORE_CONTEXT_TOOL["function"]],
        )


def _extract_more_context_request(response) -> str | None:
    for tool_call in _iter_tool_calls(response):
        name = _get_tool_name(tool_call)
        if name and name != TOOL_NAME:
            continue
        arguments = _get_tool_arguments(tool_call)
        if arguments is None:
            continue
        try:
            payload = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (TypeError, json.JSONDecodeError):
            raise ReplyModelError(
                "invalid_more_context_request", "request_more_context args are invalid"
            ) from None
        if not isinstance(payload, dict):
            raise ReplyModelError(
                "invalid_more_context_request",
                "request_more_context payload is invalid",
            )
        reason = str(payload.get("reason", "") or "").strip()
        if not reason:
            raise ReplyModelError(
                "invalid_more_context_request",
                "request_more_context reason must not be empty",
            )
        return reason
    return None


def _extract_text(response) -> str:
    if isinstance(response, str):
        return response
    choices = getattr(response, "choices", None) or []
    if choices:
        first = choices[0]
        finish_reason = getattr(first, "finish_reason", None)
        message = getattr(first, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if content is not None:
                return str(content)
            if finish_reason == "content_filter":
                raise ReplyModelError(
                    "content_filtered",
                    "model response was filtered by content safety policy",
                )
        if getattr(first, "text", None):
            return str(first.text)
    if getattr(response, "content", None):
        return str(response.content)
    return ""


def _safe_finish_reason(response) -> str:
    """Safely extract finish_reason from a model response for diagnostic logging."""
    try:
        choices = getattr(response, "choices", None) or []
        if choices:
            return str(getattr(choices[0], "finish_reason", "unknown") or "null")
    except Exception:
        pass
    return "unknown"


def _summarize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _iter_tool_calls(response):
    direct = _get_nested(response, ("tool_calls",))
    if direct:
        yield from direct
    choices = _get_nested(response, ("choices",)) or []
    for choice in choices:
        message = _get_nested(choice, ("message",))
        calls = _get_nested(message, ("tool_calls",)) or []
        yield from calls
        function_call = _get_nested(message, ("function_call",))
        if function_call is not None:
            yield {"function": function_call}
    function_call = _get_nested(response, ("function_call",))
    if function_call is not None:
        yield {"function": function_call}


def _get_nested(obj, path: tuple[str, ...]):
    current = obj
    for part in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _get_tool_name(tool_call) -> str | None:
    function = _get_nested(tool_call, ("function",))
    if function is None:
        return None
    value = _get_nested(function, ("name",))
    return str(value) if value else None


def _get_tool_arguments(tool_call) -> str | dict[str, Any] | None:
    function = _get_nested(tool_call, ("function",))
    if function is None:
        return None
    return _get_nested(function, ("arguments",))
