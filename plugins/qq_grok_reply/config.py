from dataclasses import dataclass, field

RECORDER_COMMAND_PREFIXES = ("recorder", "/recorder", "r", "/r")


@dataclass
class TargetConfig:
    groups: list[str] = field(default_factory=list)
    private: list[str] = field(default_factory=list)


@dataclass
class TriggerConfig:
    private_enabled: bool = True
    group_enabled: bool = True
    prefixes: list[str] = field(default_factory=lambda: ["/ask", "/ai", "grok"])
    allow_at: bool = True
    allow_reply_to_bot: bool = False
    ignore_self: bool = True
    ignore_recorder_command: bool = True


@dataclass
class ReadAfterWriteConfig:
    timeout_ms: int = 320
    backoff_ms: list[int] = field(default_factory=lambda: [20, 40, 80, 160])


@dataclass
class ContextConfig:
    recent_limit_group: int = 6
    recent_limit_private: int = 10
    quote_chars_group: int = 320
    quote_chars_private: int = 480
    total_chars_group: int = 1200
    total_chars_private: int = 2200
    recent_chars_group: int = 120
    recent_chars_private: int = 180


@dataclass
class CooldownConfig:
    group_chat_sec: float = 2.0
    group_user_sec: float = 5.0
    private_user_sec: float = 1.0


@dataclass
class ModelConfig:
    provider: str = "ncatbot_ai"
    model: str = ""
    temperature: float = 0.7
    max_tokens_group: int = 220
    max_tokens_private: int = 420
    timeout_sec: int = 12
    retries: int = 1
    llm_concurrency: int = 2


@dataclass
class SendConfig:
    group_use_reply_segment: bool = True
    group_at_sender: bool = False
    group_max_chars_per_part: int = 250
    private_max_chars_per_part: int = 500
    group_max_parts: int = 2
    private_max_parts: int = 3
    retry_once: bool = True


@dataclass
class TraceConfig:
    enabled: bool = True
    preview_chars: int = 240


@dataclass
class LockRetryConfig:
    enabled: bool = True
    max_retries: int = 5
    base_delay_ms: int = 50


@dataclass
class ReplyPluginSettings:
    enabled: bool = False
    recorder_db: str = ""
    monitor_all: bool = False
    targets: TargetConfig = field(default_factory=TargetConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    read_after_write: ReadAfterWriteConfig = field(default_factory=ReadAfterWriteConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    cooldown: CooldownConfig = field(default_factory=CooldownConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    send: SendConfig = field(default_factory=SendConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)
    lock_retry: LockRetryConfig = field(default_factory=LockRetryConfig)


def build_config(raw: dict) -> ReplyPluginSettings:
    targets_data = raw.get("targets", {})
    trigger_data = raw.get("trigger", {})
    read_after_write_data = raw.get("read_after_write", {})
    context_data = raw.get("context", {})
    cooldown_data = raw.get("cooldown", {})
    model_data = raw.get("model", {})
    send_data = raw.get("send", {})
    trace_data = raw.get("trace", {})
    lock_retry_data = raw.get("lock_retry", {})

    settings = ReplyPluginSettings(
        enabled=raw.get("enabled", False),
        recorder_db=raw.get("recorder_db", ""),
        monitor_all=raw.get("monitor_all", False),
        targets=TargetConfig(
            groups=[str(item) for item in targets_data.get("groups", [])],
            private=[str(item) for item in targets_data.get("private", [])],
        ),
        trigger=TriggerConfig(
            private_enabled=trigger_data.get("private_enabled", True),
            group_enabled=trigger_data.get("group_enabled", True),
            prefixes=list(trigger_data.get("prefixes", ["/ask", "/ai", "grok"])),
            allow_at=trigger_data.get("allow_at", True),
            allow_reply_to_bot=trigger_data.get("allow_reply_to_bot", False),
            ignore_self=trigger_data.get("ignore_self", True),
            ignore_recorder_command=trigger_data.get("ignore_recorder_command", True),
        ),
        read_after_write=ReadAfterWriteConfig(
            timeout_ms=read_after_write_data.get("timeout_ms", 320),
            backoff_ms=list(read_after_write_data.get("backoff_ms", [20, 40, 80, 160])),
        ),
        context=ContextConfig(
            recent_limit_group=context_data.get("recent_limit_group", 6),
            recent_limit_private=context_data.get("recent_limit_private", 10),
            quote_chars_group=context_data.get("quote_chars_group", 320),
            quote_chars_private=context_data.get("quote_chars_private", 480),
            total_chars_group=context_data.get("total_chars_group", 1200),
            total_chars_private=context_data.get("total_chars_private", 2200),
            recent_chars_group=context_data.get("recent_chars_group", 120),
            recent_chars_private=context_data.get("recent_chars_private", 180),
        ),
        cooldown=CooldownConfig(
            group_chat_sec=cooldown_data.get("group_chat_sec", 2.0),
            group_user_sec=cooldown_data.get("group_user_sec", 5.0),
            private_user_sec=cooldown_data.get("private_user_sec", 1.0),
        ),
        model=ModelConfig(
            provider=model_data.get("provider", "ncatbot_ai"),
            model=model_data.get("model", ""),
            temperature=model_data.get("temperature", 0.7),
            max_tokens_group=model_data.get("max_tokens_group", 220),
            max_tokens_private=model_data.get("max_tokens_private", 420),
            timeout_sec=model_data.get("timeout_sec", 12),
            retries=model_data.get("retries", 1),
            llm_concurrency=model_data.get("llm_concurrency", 2),
        ),
        send=SendConfig(
            group_use_reply_segment=send_data.get("group_use_reply_segment", True),
            group_at_sender=send_data.get("group_at_sender", False),
            group_max_chars_per_part=send_data.get("group_max_chars_per_part", 250),
            private_max_chars_per_part=send_data.get("private_max_chars_per_part", 500),
            group_max_parts=send_data.get("group_max_parts", 2),
            private_max_parts=send_data.get("private_max_parts", 3),
            retry_once=send_data.get("retry_once", True),
        ),
        trace=TraceConfig(
            enabled=trace_data.get("enabled", True),
            preview_chars=trace_data.get("preview_chars", 240),
        ),
        lock_retry=LockRetryConfig(
            enabled=lock_retry_data.get("enabled", True),
            max_retries=lock_retry_data.get("max_retries", 5),
            base_delay_ms=lock_retry_data.get("base_delay_ms", 50),
        ),
    )
    _validate_config(settings)
    return settings


def _validate_config(settings: ReplyPluginSettings) -> None:
    _validate_required_fields(settings)
    _validate_runtime_limits(settings)
    _validate_targets(settings)


def _validate_required_fields(settings: ReplyPluginSettings) -> None:
    if settings.enabled and not settings.recorder_db.strip():
        raise ValueError("recorder_db must be configured when qq_grok_reply is enabled")
    if settings.read_after_write.timeout_ms <= 0:
        raise ValueError("read_after_write.timeout_ms must be > 0")
    if not settings.read_after_write.backoff_ms:
        raise ValueError("read_after_write.backoff_ms must not be empty")
    if any(delay <= 0 for delay in settings.read_after_write.backoff_ms):
        raise ValueError(
            "read_after_write.backoff_ms must contain only positive values"
        )


def _validate_runtime_limits(settings: ReplyPluginSettings) -> None:
    if (
        settings.context.recent_limit_group <= 0
        or settings.context.recent_limit_private <= 0
    ):
        raise ValueError("context recent limits must be > 0")
    if (
        settings.context.quote_chars_group <= 0
        or settings.context.quote_chars_private <= 0
    ):
        raise ValueError("context quote limits must be > 0")
    if (
        settings.context.total_chars_group <= 0
        or settings.context.total_chars_private <= 0
    ):
        raise ValueError("context total limits must be > 0")
    if settings.model.timeout_sec <= 0:
        raise ValueError("model.timeout_sec must be > 0")
    if settings.model.llm_concurrency <= 0:
        raise ValueError("model.llm_concurrency must be > 0")
    if (
        settings.send.group_max_chars_per_part <= 0
        or settings.send.private_max_chars_per_part <= 0
    ):
        raise ValueError("send max chars must be > 0")
    if settings.send.group_max_parts <= 0 or settings.send.private_max_parts <= 0:
        raise ValueError("send max parts must be > 0")
    if settings.lock_retry.max_retries < 0 or settings.lock_retry.base_delay_ms <= 0:
        raise ValueError("lock_retry values are invalid")


def _validate_targets(settings: ReplyPluginSettings) -> None:
    for item in settings.targets.groups + settings.targets.private:
        if item and not str(item).isdigit():
            raise ValueError("target identifiers must contain only digits")


def is_chat_targeted(
    chat_type: str, chat_id: str, settings: ReplyPluginSettings
) -> bool:
    if settings.monitor_all:
        return True
    if chat_type == "group":
        return chat_id in settings.targets.groups
    if chat_type == "private":
        return chat_id in settings.targets.private
    return False
