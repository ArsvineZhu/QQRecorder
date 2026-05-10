from dataclasses import dataclass, field


@dataclass
class TargetConfig:
    groups: list[str] = field(default_factory=list)
    private: list[str] = field(default_factory=list)


@dataclass
class StorageConfig:
    database: str = "data/recorder.db"
    images_dir: str = "data/images"


@dataclass
class ImageConfig:
    download: bool = True
    timeout: int = 30
    max_file_size: int = 20971520


@dataclass
class ForwardConfig:
    max_depth: int = 10
    parse_content: bool = True


@dataclass
class RecorderSettings:
    targets: TargetConfig = field(default_factory=TargetConfig)
    monitor_all: bool = True
    storage: StorageConfig = field(default_factory=StorageConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    forward: ForwardConfig = field(default_factory=ForwardConfig)


DEFAULT_CONFIG = {
    "monitor_all": True,
    "targets": {"groups": [], "private": []},
    "storage": {"database": "data/recorder.db", "images_dir": "data/images"},
    "image": {"download": True, "timeout": 30, "max_file_size": 20971520},
    "forward": {"max_depth": 10, "parse_content": True},
}


def build_config(raw: dict) -> RecorderSettings:
    targets_data = raw.get("targets", {})
    storage_data = raw.get("storage", {})
    image_data = raw.get("image", {})
    forward_data = raw.get("forward", {})

    targets = TargetConfig(
        groups=targets_data.get("groups", []),
        private=targets_data.get("private", []),
    )
    storage = StorageConfig(
        database=storage_data.get("database", DEFAULT_CONFIG["storage"]["database"]),
        images_dir=storage_data.get(
            "images_dir", DEFAULT_CONFIG["storage"]["images_dir"]
        ),
    )
    image = ImageConfig(
        download=image_data.get("download", True),
        timeout=image_data.get("timeout", 30),
        max_file_size=image_data.get("max_file_size", 20971520),
    )
    forward = ForwardConfig(
        max_depth=forward_data.get("max_depth", 10),
        parse_content=forward_data.get("parse_content", True),
    )

    config = RecorderSettings(
        targets=targets,
        monitor_all=raw.get("monitor_all", True),
        storage=storage,
        image=image,
        forward=forward,
    )

    _validate_config(config)
    return config


def _validate_config(config: RecorderSettings) -> None:
    if not config.storage.database.strip():
        raise ValueError("storage.database must be a non-empty string")
    if not config.storage.images_dir.strip():
        raise ValueError("storage.images_dir must be a non-empty string")
    if config.image.timeout <= 0:
        raise ValueError("image.timeout must be > 0")
    if config.image.max_file_size <= 0:
        raise ValueError("image.max_file_size must be > 0")
    if config.forward.max_depth <= 0 or config.forward.max_depth > 50:
        raise ValueError("forward.max_depth must be > 0 and <= 50")
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
