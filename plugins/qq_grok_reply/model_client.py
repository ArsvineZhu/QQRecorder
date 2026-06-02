import asyncio

from .context_builder import BuiltContext
from .prompt import build_prompt_messages


class ReplyModelError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


async def generate_reply(
    api, ctx: BuiltContext, settings
) -> tuple[str, dict[str, str]]:
    messages = build_prompt_messages(ctx)
    retries = max(0, settings.model.retries)
    max_tokens = (
        settings.model.max_tokens_group
        if ctx.chat_type == "group" or ctx.variant.startswith("group")
        else settings.model.max_tokens_private
    )
    preview_chars = settings.trace.preview_chars
    last_error: Exception | None = None

    try:
        async with asyncio.timeout(settings.model.timeout_sec):
            for _attempt in range(retries + 1):
                try:
                    response = await api.ai.chat(
                        messages,
                        model=settings.model.model or None,
                        temperature=settings.model.temperature,
                        max_tokens=max_tokens,
                    )
                    text = _extract_text(response).strip()
                    if not text:
                        raise ReplyModelError(
                            "empty_response", "model returned empty content"
                        )
                    return text, {
                        "model_name": str(
                            getattr(response, "model", None)
                            or settings.model.model
                            or ""
                        ),
                        "model_request_summary": _summarize(
                            messages[-1]["content"], preview_chars
                        ),
                        "model_response_summary": _summarize(text, preview_chars),
                    }
                except ReplyModelError:
                    raise
                except Exception as exc:
                    last_error = exc
            raise ReplyModelError("llm_error", str(last_error or "unknown model error"))
    except TimeoutError as exc:
        raise ReplyModelError("llm_timeout", "model request timed out") from exc


def _extract_text(response) -> str:
    if isinstance(response, str):
        return response
    choices = getattr(response, "choices", None) or []
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        if message is not None and getattr(message, "content", None):
            return str(message.content)
        if getattr(first, "text", None):
            return str(first.text)
    if getattr(response, "content", None):
        return str(response.content)
    return ""


def _summarize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"
