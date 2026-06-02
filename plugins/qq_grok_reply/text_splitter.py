def split_text(text: str, max_chars: int, max_parts: int) -> list[str]:
    if not text:
        return [""]
    if len(text) <= max_chars:
        return [text]

    remaining = text
    parts: list[str] = []
    while remaining and len(parts) < max_parts:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        if len(parts) == max_parts - 1:
            parts.append(remaining[:max_chars].rstrip())
            break
        chunk, remaining = _take_chunk(remaining, max_chars)
        parts.append(chunk.rstrip())
        remaining = remaining.lstrip()
    return [part for part in parts if part]


def _take_chunk(text: str, max_chars: int) -> tuple[str, str]:
    for separator in ("\n\n", "\n", "。", "！", "？", "；", "，", " "):
        idx = text.rfind(separator, 0, max_chars + 1)
        if idx > 0:
            end = idx + len(separator)
            return text[:end], text[end:]
    return text[:max_chars], text[max_chars:]
