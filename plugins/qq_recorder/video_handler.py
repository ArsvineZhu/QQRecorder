import asyncio
import datetime
import hashlib
import os
import re
from dataclasses import dataclass

import aiohttp

from .config import VideoConfig
from .message_parser import VideoInfo


class VideoDownloadError(Exception):
    pass


@dataclass
class VideoResult:
    local_path: str
    file_unique: str
    file_size: int
    success: bool
    error: str = ""


def generate_video_path(
    base_dir: str, filename: str, date: datetime.datetime | None = None
) -> str:
    if date is None:
        date = datetime.datetime.now()
    date_path = os.path.join(
        base_dir, str(date.year), f"{date.month:02d}", f"{date.day:02d}"
    )
    os.makedirs(date_path, exist_ok=True)
    return os.path.abspath(os.path.join(date_path, filename))


_CONTENT_TYPE_MAP: dict[str, str] = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "video/webm": "webm",
}


def detect_video_extension(url: str = "", content_type: str = "") -> str:
    if url:
        match = re.search(r"\.(mp4|mov|avi|mkv|webm)", url, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    if content_type:
        mime = content_type.split(";")[0].strip().lower()
        return _CONTENT_TYPE_MAP.get(mime, "mp4")
    return "mp4"


def generate_video_filename(
    file_unique: str,
    url: str = "",
    content_type: str = "",
) -> str:
    base = (
        file_unique
        if file_unique and file_unique != "0"
        else f"{int(datetime.datetime.now().timestamp()):x}_{os.urandom(4).hex()}"
    )
    ext = detect_video_extension(url, content_type)
    sanitized_base = re.sub(r"[^\w\-_.]", "_", base)
    return f"{sanitized_base}.{ext}"


async def download_video(
    url: str,
    *,
    timeout: int = 60,
    max_size: int = 524288000,
    session: aiohttp.ClientSession | None = None,
) -> tuple[bytes, dict]:
    own_session = session is None
    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        if own_session:
            session = aiohttp.ClientSession(timeout=timeout_obj)
        assert session is not None
        async with session.get(url) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_size:
                raise VideoDownloadError(
                    f"File too large: {content_length} bytes > {max_size} bytes"
                )
            chunks: list[bytes] = []
            total_bytes = 0
            async for chunk in response.content.iter_chunked(128 * 1024):
                total_bytes += len(chunk)
                if total_bytes > max_size:
                    raise VideoDownloadError(
                        f"File too large: {total_bytes} bytes > {max_size} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks), dict(response.headers)
    except Exception as exc:
        raise VideoDownloadError(f"Download failed: {str(exc)}") from exc
    finally:
        if own_session and session is not None:
            await session.close()


async def save_video(video_data: bytes, filepath: str) -> str:
    def _save():
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as file_obj:
            file_obj.write(video_data)
        return filepath

    return await asyncio.to_thread(_save)


async def process_video(
    video_info: VideoInfo,
    config_storage_dir: str,
    config_video: VideoConfig,
    session: aiohttp.ClientSession | None = None,
    download_semaphore: asyncio.Semaphore | None = None,
) -> VideoResult:
    local_path = str(video_info.local_path or "")
    if local_path and os.path.isfile(local_path):
        return VideoResult(
            local_path=os.path.abspath(local_path),
            file_unique=video_info.file_unique or _hash_file(local_path),
            file_size=video_info.file_size or os.path.getsize(local_path),
            success=True,
        )

    if not video_info.file_url:
        return VideoResult(
            local_path="",
            file_unique=video_info.file_unique,
            file_size=video_info.file_size,
            success=False,
            error="Empty URL",
        )

    async def _download():
        return await download_video(
            video_info.file_url,
            timeout=config_video.timeout,
            max_size=config_video.max_file_size,
            session=session,
        )

    try:
        if download_semaphore is None:
            video_bytes, headers = await _download()
        else:
            async with download_semaphore:
                video_bytes, headers = await _download()
        file_unique = hashlib.md5(video_bytes).hexdigest().lower()
        filename = generate_video_filename(
            file_unique,
            video_info.file_url,
            headers.get("Content-Type", ""),
        )
        filepath = generate_video_path(config_storage_dir, filename)
        await save_video(video_bytes, filepath)
        return VideoResult(
            local_path=filepath,
            file_unique=file_unique,
            file_size=len(video_bytes),
            success=True,
        )
    except VideoDownloadError as exc:
        return VideoResult(
            local_path="",
            file_unique=video_info.file_unique,
            file_size=video_info.file_size,
            success=False,
            error=str(exc),
        )


async def process_videos(
    videos: list[VideoInfo],
    config_storage_dir: str,
    config_video: VideoConfig,
    download_semaphore: asyncio.Semaphore | None = None,
) -> list[VideoResult]:
    results: list[VideoResult] = []
    if not config_video.download:
        for video in videos:
            results.append(
                VideoResult(
                    local_path=video.local_path,
                    file_unique=video.file_unique,
                    file_size=video.file_size,
                    success=False,
                    error="Download disabled",
                )
            )
        return results

    timeout_obj = aiohttp.ClientTimeout(total=config_video.timeout)
    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        for video in videos:
            results.append(
                await process_video(
                    video,
                    config_storage_dir,
                    config_video,
                    session=session,
                    download_semaphore=download_semaphore,
                )
            )
    return results


def _hash_file(path: str) -> str:
    with open(path, "rb") as file_obj:
        return hashlib.md5(file_obj.read()).hexdigest().lower()
