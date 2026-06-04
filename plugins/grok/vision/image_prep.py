from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps


@dataclass(slots=True)
class PreparedImage:
    data: bytes
    mime_type: str


def prepare_for_api(image_bytes: bytes, *, max_bytes: int) -> PreparedImage:
    original_mime = _guess_image_mime(image_bytes)
    if len(image_bytes) <= max_bytes:
        return PreparedImage(image_bytes, original_mime)

    image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes)))
    if getattr(image, "is_animated", False):
        image.seek(0)

    if _has_alpha(image):
        prepared = _compress_png(image, max_bytes)
        if prepared is not None:
            return prepared

    prepared = _compress_jpeg(_flatten_to_rgb(image), max_bytes)
    if prepared is not None:
        return prepared

    fallback = _compress_jpeg(_flatten_to_rgb(image), max_bytes, min_side=16)
    if fallback is not None:
        return fallback
    return PreparedImage(image_bytes, original_mime)


def _compress_png(image: Image.Image, max_bytes: int) -> PreparedImage | None:
    best: bytes | None = None
    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2):
        resized = _resize_image(image, scale)
        candidate = _save_image(resized, "PNG", optimize=True, compress_level=9)
        if best is None or len(candidate) < len(best):
            best = candidate
        if len(candidate) <= max_bytes:
            return PreparedImage(candidate, "image/png")
    if best is not None and len(best) <= max_bytes:
        return PreparedImage(best, "image/png")
    return None


def _compress_jpeg(
    image: Image.Image,
    max_bytes: int,
    *,
    min_side: int = 64,
) -> PreparedImage | None:
    best: bytes | None = None
    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2):
        resized = _resize_image(image, scale, min_side=min_side)
        for quality in (85, 75, 65, 55, 45, 35, 25):
            candidate = _save_image(
                resized,
                "JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            if best is None or len(candidate) < len(best):
                best = candidate
            if len(candidate) <= max_bytes:
                return PreparedImage(candidate, "image/jpeg")
    if best is not None and len(best) <= max_bytes:
        return PreparedImage(best, "image/jpeg")
    return None


def _resize_image(
    image: Image.Image,
    scale: float,
    *,
    min_side: int = 64,
) -> Image.Image:
    if scale >= 0.999:
        return image.copy()
    width = max(min_side, int(image.width * scale))
    height = max(min_side, int(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _save_image(image: Image.Image, fmt: str, **kwargs) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGB", "L"):
        return image.convert("RGB")
    canvas = Image.new("RGB", image.size, (255, 255, 255))
    alpha = image.getchannel("A") if "A" in image.getbands() else None
    canvas.paste(image.convert("RGBA"), mask=alpha)
    return canvas


def _has_alpha(image: Image.Image) -> bool:
    return "A" in image.getbands() or image.mode in {"RGBA", "LA", "PA"}


def _guess_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
