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
    prefixes: list[str] = field(default_factory=lambda: ["/agent", "/ctx", "agent"])
    allow_at: bool = True
    allow_reply_to_bot: bool = False
    ignore_self: bool = True
    ignore_recorder_command: bool = True


@dataclass
class ReadAfterWriteConfig:
    timeout_ms: int = 2000
    backoff_ms: list[int] = field(default_factory=lambda: [50, 100, 200, 400, 800])


@dataclass
class AgentConfig:
    max_steps: int = 4
    max_tool_calls_per_turn: int = 3
    max_evidence_chars: int = 6000


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
    thinking_enabled: bool = False
    thinking_effort: str = "high"


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
    log_llm_chain: bool = False


@dataclass
class LockRetryConfig:
    enabled: bool = True
    max_retries: int = 5
    base_delay_ms: int = 50


@dataclass
class VisionConfig:
    enabled: bool = False
    dashscope_api_key: str = ""
    image_fast_model: str = "qwen3-vl-flash"
    image_detail_model: str = "qwen3-vl-plus"
    image_deep_semantic_model: str = "qwen3.7-plus"
    video_summary_model: str = "qwen3.6-flash"
    temperature: float = 0.4
    timeout_sec: int = 20
    source_image_bytes_threshold: int = 50 * 1024 * 1024
    api_image_bytes_max: int = 10 * 1024 * 1024
    max_images_per_message: int = 3
    include_in_context: bool = True
    cache_enabled: bool = True
    cache_ttl_days: int = 30
    prompt_version: str = "visual_v1"
    schema_version: str = "visual_semantic_json_v1"
    daily_limit_image_per_user_chat: int = 30
    daily_limit_image_global: int = 500
    daily_limit_video_per_user_chat: int = 3
    daily_limit_video_global: int = 20
    router_image_bytes_threshold: int = 1 * 1024 * 1024
    escalation_enabled: bool = True
    escalation_min_confidence: float = 0.65
    escalation_max_images_escalate: int = 1
    escalation_detail_screenshot_types: list[str] = field(
        default_factory=lambda: ["screenshot", "document"]
    )
    video_max_duration_min: int = 30
    video_max_bytes: int = 500 * 1024 * 1024
    video_timeout_sec: int = 60


@dataclass
class PromptConfig:
    system_template_path: str = "prompt/system.md"


@dataclass
class ProfileConfig:
    db_path: str = "data/profiles.json"


@dataclass
class AgentPluginSettings:
    enabled: bool = False
    recorder_db: str = ""
    monitor_all: bool = False
    targets: TargetConfig = field(default_factory=TargetConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    read_after_write: ReadAfterWriteConfig = field(default_factory=ReadAfterWriteConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    send: SendConfig = field(default_factory=SendConfig)
    trace: TraceConfig = field(default_factory=TraceConfig)
    lock_retry: LockRetryConfig = field(default_factory=LockRetryConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
