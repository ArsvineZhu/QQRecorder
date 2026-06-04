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
    timeout_ms: int = 2000
    backoff_ms: list[int] = field(default_factory=lambda: [50, 100, 200, 400, 800])


@dataclass
class ContextConfig:
    mode: str = "topic_ai"
    recent_limit_group: int = 6
    recent_limit_private: int = 10
    local_recent_limit_group: int = 30
    local_recent_limit_private: int = 30
    local_recent_time_window_minutes_group: int = 30
    local_recent_time_window_minutes_private: int = 30
    quote_chain_max_depth_group: int = 10
    quote_chain_max_depth_private: int = 10
    quote_neighbor_limit_group: int = 10
    quote_neighbor_limit_private: int = 10
    quote_chars_group: int = 320
    quote_chars_private: int = 480
    total_chars_group: int = 6000
    total_chars_private: int = 2200
    recent_chars_group: int = 120
    recent_chars_private: int = 180
    candidate_limit_group: int = 80
    candidate_limit_private: int = 30
    candidate_time_window_minutes_group: int = 45
    candidate_time_window_minutes_private: int = 30
    selected_max_messages_group: int = 20
    selected_max_messages_private: int = 12
    forward_max_items: int = 12
    forward_max_chars: int = 1600
    fallback_recent_limit_group: int = 16
    fallback_recent_limit_private: int = 12


@dataclass
class TopicAnalyzerConfig:
    enabled: bool = True
    model: str = ""
    temperature: float = 0.2
    timeout_sec: int = 8
    min_confidence: float = 0.45
    fallback_to_recent: bool = True
    max_summary_chars: int = 800


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
    log_runtime: bool = True
    log_context_blocks: bool = False
    log_chars: int = 4000
    pretty_print: bool = False


@dataclass
class LockRetryConfig:
    enabled: bool = True
    max_retries: int = 5
    base_delay_ms: int = 50


@dataclass
class VisionConfig:
    enabled: bool = False
    dashscope_api_key: str = ""

    # Phase 2: model routing (image_fast replaces Phase 1's single image_model)
    image_fast_model: str = "qwen3-vl-flash"
    image_detail_model: str = "qwen3-vl-plus"
    image_deep_semantic_model: str = "qwen3.7-plus"
    video_summary_model: str = "qwen3.6-flash"

    # Common parameters
    temperature: float = 0.4
    timeout_sec: int = 20
    # Size gating: source is the skip-above limit, api is the compress-to limit
    source_image_bytes_threshold: int = 50 * 1024 * 1024
    api_image_bytes_max: int = 10 * 1024 * 1024
    max_images_per_message: int = 3
    include_in_context: bool = True

    # Cache
    cache_enabled: bool = True
    cache_ttl_days: int = 30
    prompt_version: str = "visual_v1"
    schema_version: str = "visual_semantic_json_v1"

    # Quota
    daily_limit_image_per_user_chat: int = 30
    daily_limit_image_global: int = 500
    daily_limit_video_per_user_chat: int = 3
    daily_limit_video_global: int = 20

    # Phase 2: routing
    router_image_bytes_threshold: int = 1 * 1024 * 1024

    # Phase 2: escalation
    escalation_enabled: bool = True
    escalation_min_confidence: float = 0.65
    escalation_max_images_escalate: int = 1
    escalation_detail_screenshot_types: list[str] = field(
        default_factory=lambda: ["screenshot", "document"]
    )

    # Phase 2: video
    video_max_duration_min: int = 30
    video_max_bytes: int = 500 * 1024 * 1024
    video_timeout_sec: int = 60


@dataclass
class ReplyPluginSettings:
    enabled: bool = False
    recorder_db: str = ""
    monitor_all: bool = False
    targets: TargetConfig = field(default_factory=TargetConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    read_after_write: ReadAfterWriteConfig = field(default_factory=ReadAfterWriteConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    topic_analyzer: TopicAnalyzerConfig = field(default_factory=TopicAnalyzerConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    cooldown: CooldownConfig = field(default_factory=CooldownConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    send: SendConfig = field(default_factory=SendConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)
    lock_retry: LockRetryConfig = field(default_factory=LockRetryConfig)
