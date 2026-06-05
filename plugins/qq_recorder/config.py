from dataclasses import dataclass, field
from datetime import datetime


def _validate_hhmm(value: str) -> None:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"Invalid time format: {value!r}, expected HH:MM") from exc
    if parsed.hour < 0 or parsed.hour > 23 or parsed.minute < 0 or parsed.minute > 59:
        raise ValueError(f"Invalid time value: {value!r}")


@dataclass
class TargetConfig:
    groups: list[str] = field(default_factory=list)
    private: list[str] = field(default_factory=list)


@dataclass
class StorageConfig:
    database: str = "data/recorder.db"
    images_dir: str = "data/images"
    videos_dir: str = "data/videos"
    lock_retry: "LockRetryConfig" = field(default_factory=lambda: LockRetryConfig())


@dataclass
class LockRetryConfig:
    enabled: bool = True
    max_retries: int = 5
    base_delay_ms: int = 50


@dataclass
class ImageConfig:
    download: bool = True
    timeout: int = 30
    max_file_size: int = 52428800


@dataclass
class VideoConfig:
    download: bool = True
    timeout: int = 60
    max_file_size: int = 524288000
    max_duration_sec: int = 1800


@dataclass
class ProcessingConfig:
    max_inflight: int = 48
    image_download_concurrency: int = 4
    video_download_concurrency: int = 2


@dataclass
class ForwardConfig:
    max_depth: int = 10
    parse_content: bool = True


@dataclass
class BackupConfig:
    enabled: bool = True
    output_dir: str = "data/backups"
    keep_last: int = 7
    full_interval_days: int = 7
    full_time: str = "03:00"
    incremental_times: list[str] = field(default_factory=lambda: ["12:00", "18:00"])


@dataclass
class RecorderSettings:
    targets: TargetConfig = field(default_factory=TargetConfig)
    monitor_all: bool = True
    storage: StorageConfig = field(default_factory=StorageConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    forward: ForwardConfig = field(default_factory=ForwardConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)


DEFAULT_CONFIG = {
    "monitor_all": True,
    "targets": {"groups": [], "private": []},
    "storage": {
        "database": "data/recorder.db",
        "images_dir": "data/images",
        "videos_dir": "data/videos",
        "lock_retry": {"enabled": True, "max_retries": 5, "base_delay_ms": 50},
    },
    "image": {"download": True, "timeout": 30, "max_file_size": 52428800},
    "video": {
        "download": True,
        "timeout": 60,
        "max_file_size": 524288000,
        "max_duration_sec": 1800,
    },
    "processing": {
        "max_inflight": 48,
        "image_download_concurrency": 4,
        "video_download_concurrency": 2,
    },
    "forward": {"max_depth": 10, "parse_content": True},
    "backup": {
        "enabled": True,
        "output_dir": "data/backups",
        "keep_last": 7,
        "full_interval_days": 7,
        "full_time": "03:00",
        "incremental_times": ["12:00", "18:00"],
    },
}


def build_config(raw: dict) -> RecorderSettings:
    targets_data = raw.get("targets", {})
    storage_data = raw.get("storage", {})
    lock_retry_data = storage_data.get("lock_retry", {})
    image_data = raw.get("image", {})
    video_data = raw.get("video", {})
    processing_data = raw.get("processing", {})
    forward_data = raw.get("forward", {})
    backup_data = raw.get("backup", {})

    targets = TargetConfig(
        groups=targets_data.get("groups", []),
        private=targets_data.get("private", []),
    )
    lock_retry = LockRetryConfig(
        enabled=lock_retry_data.get(
            "enabled", DEFAULT_CONFIG["storage"]["lock_retry"]["enabled"]
        ),
        max_retries=lock_retry_data.get(
            "max_retries", DEFAULT_CONFIG["storage"]["lock_retry"]["max_retries"]
        ),
        base_delay_ms=lock_retry_data.get(
            "base_delay_ms", DEFAULT_CONFIG["storage"]["lock_retry"]["base_delay_ms"]
        ),
    )
    storage = StorageConfig(
        database=storage_data.get("database", DEFAULT_CONFIG["storage"]["database"]),
        images_dir=storage_data.get(
            "images_dir", DEFAULT_CONFIG["storage"]["images_dir"]
        ),
        videos_dir=storage_data.get(
            "videos_dir", DEFAULT_CONFIG["storage"]["videos_dir"]
        ),
        lock_retry=lock_retry,
    )
    image = ImageConfig(
        download=image_data.get("download", True),
        timeout=image_data.get("timeout", 30),
        max_file_size=image_data.get("max_file_size", 52428800),
    )
    video = VideoConfig(
        download=video_data.get("download", True),
        timeout=video_data.get("timeout", 60),
        max_file_size=video_data.get("max_file_size", 524288000),
        max_duration_sec=video_data.get("max_duration_sec", 1800),
    )
    processing = ProcessingConfig(
        max_inflight=processing_data.get(
            "max_inflight", DEFAULT_CONFIG["processing"]["max_inflight"]
        ),
        image_download_concurrency=processing_data.get(
            "image_download_concurrency",
            DEFAULT_CONFIG["processing"]["image_download_concurrency"],
        ),
        video_download_concurrency=processing_data.get(
            "video_download_concurrency",
            DEFAULT_CONFIG["processing"]["video_download_concurrency"],
        ),
    )
    forward = ForwardConfig(
        max_depth=forward_data.get("max_depth", 10),
        parse_content=forward_data.get("parse_content", True),
    )
    backup = BackupConfig(
        enabled=backup_data.get("enabled", True),
        output_dir=backup_data.get(
            "output_dir", DEFAULT_CONFIG["backup"]["output_dir"]
        ),
        keep_last=backup_data.get("keep_last", 7),
        full_interval_days=backup_data.get(
            "full_interval_days", DEFAULT_CONFIG["backup"]["full_interval_days"]
        ),
        full_time=backup_data.get("full_time", DEFAULT_CONFIG["backup"]["full_time"]),
        incremental_times=list(
            backup_data.get(
                "incremental_times", DEFAULT_CONFIG["backup"]["incremental_times"]
            )
        ),
    )

    config = RecorderSettings(
        targets=targets,
        monitor_all=raw.get("monitor_all", True),
        storage=storage,
        image=image,
        video=video,
        processing=processing,
        forward=forward,
        backup=backup,
    )

    _validate_config(config)
    return config


def _validate_config(config: RecorderSettings) -> None:  # noqa: C901
    if not config.storage.database.strip():
        raise ValueError("storage.database must be a non-empty string")
    if not config.storage.images_dir.strip():
        raise ValueError("storage.images_dir must be a non-empty string")
    if not config.storage.videos_dir.strip():
        raise ValueError("storage.videos_dir must be a non-empty string")
    if config.storage.lock_retry.max_retries < 0:
        raise ValueError("storage.lock_retry.max_retries must be >= 0")
    if config.storage.lock_retry.base_delay_ms <= 0:
        raise ValueError("storage.lock_retry.base_delay_ms must be > 0")
    if config.image.timeout <= 0:
        raise ValueError("image.timeout must be > 0")
    if config.image.max_file_size <= 0:
        raise ValueError("image.max_file_size must be > 0")
    if config.video.timeout <= 0:
        raise ValueError("video.timeout must be > 0")
    if config.video.max_file_size <= 0:
        raise ValueError("video.max_file_size must be > 0")
    if config.video.max_duration_sec <= 0:
        raise ValueError("video.max_duration_sec must be > 0")
    if config.processing.max_inflight <= 0:
        raise ValueError("processing.max_inflight must be > 0")
    if config.processing.image_download_concurrency <= 0:
        raise ValueError("processing.image_download_concurrency must be > 0")
    if config.processing.video_download_concurrency <= 0:
        raise ValueError("processing.video_download_concurrency must be > 0")
    if config.forward.max_depth <= 0 or config.forward.max_depth > 50:
        raise ValueError("forward.max_depth must be > 0 and <= 50")
    if not config.backup.output_dir.strip():
        raise ValueError("backup.output_dir must be a non-empty string")
    if config.backup.keep_last <= 0:
        raise ValueError("backup.keep_last must be > 0")
    if config.backup.full_interval_days <= 0:
        raise ValueError("backup.full_interval_days must be > 0")
    _validate_hhmm(config.backup.full_time)
    if config.backup.enabled and not config.backup.incremental_times:
        raise ValueError("backup.incremental_times must not be empty when enabled")
    seen_times: set[str] = set()
    for time_str in config.backup.incremental_times:
        _validate_hhmm(time_str)
        if time_str == config.backup.full_time:
            raise ValueError("backup.full_time must not duplicate incremental times")
        if time_str in seen_times:
            raise ValueError("backup.incremental_times must not contain duplicates")
        seen_times.add(time_str)
    for group_id in config.targets.groups:
        if not group_id.isdigit():
            raise ValueError("Group IDs must contain only digits")
    for qq in config.targets.private:
        if not qq.isdigit():
            raise ValueError("QQ numbers must contain only digits")
    if not config.targets.groups and not config.targets.private:
        config.monitor_all = True


def is_chat_monitored(chat_type: str, chat_id: str, config: RecorderSettings) -> bool:
    if config.monitor_all:
        return True
    if chat_type == "group":
        return chat_id in config.targets.groups
    elif chat_type == "private":
        return chat_id in config.targets.private
    return False
