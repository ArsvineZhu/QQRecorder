import asyncio
import datetime
import hashlib
import os
import re
from dataclasses import dataclass

import aiohttp

from .config import ImageConfig
from .message_parser import ImageInfo


class ImageDownloadError(Exception):
    pass


@dataclass
class ImageResult:
    local_path: str
    file_unique: str
    file_size: int
    success: bool
    error: str = ""


def generate_image_path(
    base_dir: str, filename: str, date: datetime.datetime | None = None
) -> str:
    if date is None:
        date = datetime.datetime.now()
    date_path = os.path.join(
        base_dir, str(date.year), f"{date.month:02d}", f"{date.day:02d}"
    )
    os.makedirs(date_path, exist_ok=True)
    return os.path.abspath(os.path.join(date_path, filename))


_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"GIF8", "gif"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"RIFF", "webp"),
    (b"BM", "bmp"),
]

_CONTENT_TYPE_MAP: dict[str, str] = {
    "image/gif": "gif",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/bmp": "bmp",
}


def detect_extension_from_url(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"\.(jpg|jpeg|png|gif|bmp|webp)", url, re.IGNORECASE)
    if match:
        ext = match.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    return ""


def detect_extension_from_content_type(content_type: str) -> str:
    if not content_type:
        return ""
    mime = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_MAP.get(mime, "")


def detect_extension_from_magic(data: bytes) -> str:
    if not data or len(data) < 4:
        return ""
    for signature, ext in _MAGIC_SIGNATURES:
        if data[: len(signature)] == signature:
            if ext == "webp" and len(data) >= 12:
                if data[8:12] != b"WEBP":
                    continue
            return ext
    return ""


def detect_extension(
    url: str = "", content_type: str = "", image_data: bytes = b""
) -> str:
    ext = detect_extension_from_url(url)
    if ext:
        return ext
    ext = detect_extension_from_content_type(content_type)
    if ext:
        return ext
    ext = detect_extension_from_magic(image_data)
    if ext:
        return ext
    return "jpg"


def generate_filename(
    file_unique: str, url: str = "", content_type: str = "", image_data: bytes = b""
) -> str:
    base = (
        file_unique
        if file_unique and file_unique != "0"
        else f"{int(datetime.datetime.now().timestamp()):x}_{os.urandom(4).hex()}"
    )
    ext = detect_extension(url, content_type, image_data)
    sanitized_base = re.sub(r"[^\w\-_.]", "_", base)
    return f"{sanitized_base}.{ext}"


def calculate_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest().lower()


async def download_image(
    url: str,
    timeout: int = 30,
    max_size: int = 20971520,
    session: aiohttp.ClientSession | None = None,
) -> tuple[bytes, dict]:
    own_session = session is None
    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        if own_session:
            session = aiohttp.ClientSession(timeout=timeout_obj)
        async with session.get(url) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_size:
                raise ImageDownloadError(
                    f"File too large: {content_length} bytes > {max_size} bytes"
                )
            chunks: list[bytes] = []
            total_bytes = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                total_bytes += len(chunk)
                if total_bytes > max_size:
                    raise ImageDownloadError(
                        f"File too large: {total_bytes} bytes > {max_size} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks), dict(response.headers)
    except Exception as e:
        raise ImageDownloadError(f"Download failed: {str(e)}") from e
    finally:
        if own_session:
            assert session is not None
            await session.close()


async def save_image(image_data: bytes, filepath: str) -> str:
    def _save():
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(image_data)
        return filepath

    return await asyncio.to_thread(_save)


async def process_image(
    image_info: ImageInfo,
    config_storage_dir: str,
    config_image: ImageConfig,
    session: aiohttp.ClientSession | None = None,
    download_semaphore: asyncio.Semaphore | None = None,
) -> ImageResult:
    try:
        if not image_info.file_url:
            return ImageResult(
                local_path="",
                file_unique="",
                file_size=0,
                success=False,
                error="Empty URL",
            )

        async def _download() -> tuple[bytes, dict]:
            return await download_image(
                image_info.file_url,
                timeout=config_image.timeout,
                max_size=config_image.max_file_size,
                session=session,
            )

        if download_semaphore is None:
            image_data, headers = await _download()
        else:
            async with download_semaphore:
                image_data, headers = await _download()

        md5_hash = calculate_md5(image_data)
        content_type = headers.get("Content-Type", "")
        filename = generate_filename(
            md5_hash, image_info.file_url, content_type, image_data
        )
        filepath = generate_image_path(config_storage_dir, filename)
        await save_image(image_data, filepath)
        return ImageResult(
            local_path=filepath,
            file_unique=md5_hash,
            file_size=len(image_data),
            success=True,
        )
    except ImageDownloadError as e:
        return ImageResult(
            local_path="", file_unique="", file_size=0, success=False, error=str(e)
        )
    except Exception as e:
        return ImageResult(
            local_path="",
            file_unique="",
            file_size=0,
            success=False,
            error=f"Processing failed: {str(e)}",
        )


async def process_images(
    images: list[ImageInfo],
    config_storage_dir: str,
    config_image: ImageConfig,
    download_semaphore: asyncio.Semaphore | None = None,
) -> list[ImageResult]:
    results = []
    if not config_image.download:
        for img in images:
            results.append(
                ImageResult(
                    local_path="",
                    file_unique=img.file_unique,
                    file_size=img.file_size,
                    success=False,
                    error="Download disabled",
                )
            )
        return results
    timeout_obj = aiohttp.ClientTimeout(total=config_image.timeout)
    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        for img in images:
            if not img.file_url:
                results.append(
                    ImageResult(
                        local_path="",
                        file_unique=img.file_unique,
                        file_size=img.file_size,
                        success=False,
                        error="Empty URL",
                    )
                )
                continue
            result = await process_image(
                img,
                config_storage_dir,
                config_image,
                session=session,
                download_semaphore=download_semaphore,
            )
            results.append(result)
    return results
