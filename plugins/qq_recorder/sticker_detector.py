"""Sticker detection for QQ messages.

Three-layer detection pipeline based on real QQ message data:
1. Metadata parsing (QQ segment fields - PRIMARY: sub_type in segment_data)
2. Text matching (CQ code patterns in raw_message)
3. Heuristics (file format + size as fallback)

From actual DB analysis:
- sub_type=0: regular image (no summary, photo/ screenshot)
- sub_type=1: animated expression / big-face sticker (summary=[动画表情])
- sub_type=7: QQ shop sticker / premium sticker (summary=[name])
- sub_type=13: other sticker type (rare)
"""


def _has_sticker_cq_code(raw_message: str) -> bool:
    """Check if raw_message CQ code contains sticker indicators.

    Sticker images in CQ code always include sub_type != 0:
      [CQ:image,summary=...,sub_type=1,url=...,file_size=...]
    Regular images omit summary and use sub_type=0:
      [CQ:image,file=...,sub_type=0,url=...,file_size=...]
    """
    if not raw_message:
        return False
    return any(f"sub_type={v}" in raw_message for v in (1, 7, 13))


def detect_by_text(raw_message: str) -> tuple[bool, float]:
    """Detect sticker from CQ code patterns in raw_message text."""
    if not raw_message:
        return False, 0.0
    if _has_sticker_cq_code(raw_message):
        return True, 0.95
    return False, 0.0


def _get_data(segment_data: dict) -> dict:
    """Extract the inner data dict from segment_data."""
    if not isinstance(segment_data, dict):
        return {}
    inner = segment_data.get("data", segment_data)
    if isinstance(inner, dict):
        return inner
    return {}


def detect_by_metadata(segment_data: dict) -> tuple[bool, float]:
    """Detect sticker from segment metadata fields.

    Real QQ image segment_data keys: file, file_size, sub_type, summary, url
    - sub_type != 0: primary sticker indicator
    - summary non-empty: confirms it is a sticker with a name
    """
    data = _get_data(segment_data)
    if not data:
        return False, 0.0

    sub_type = data.get("sub_type")
    if sub_type is not None and sub_type != 0:
        if sub_type == 1:
            return True, 0.95
        if sub_type == 7:
            return True, 0.9
        return True, 0.85

    summary = data.get("summary")
    if summary:
        return True, 0.8

    return False, 0.0


def detect_by_heuristics(
    local_path: str | None = None,
    file_size: int | None = None,
    file_ext: str | None = None,
) -> tuple[bool, float]:
    """Detect sticker from file format and size as fallback."""
    format_hit = False
    size_hit = False

    if file_ext:
        ext = file_ext.lower().lstrip(".")
        if ext in ("gif", "webp"):
            format_hit = True

    if file_size is not None and file_size > 0:
        if file_size < 100 * 1024:
            size_hit = True

    if format_hit and size_hit:
        return True, 0.85
    if format_hit:
        return True, 0.7
    if size_hit:
        return True, 0.5

    return False, 0.0


def combined_detection(
    raw_message: str,
    segment_data: dict,
    local_path: str | None = None,
    file_size: int | None = None,
    file_ext: str | None = None,
) -> tuple[bool, float]:
    """Combined detection using all three methods. Takes highest confidence."""
    _meta_r, meta_conf = detect_by_metadata(segment_data)
    _text_r, text_conf = detect_by_text(raw_message)
    _heur_r, heur_conf = detect_by_heuristics(local_path, file_size, file_ext)

    best_conf = max(meta_conf, text_conf, heur_conf)
    is_sticker = best_conf >= 0.7
    return is_sticker, best_conf
