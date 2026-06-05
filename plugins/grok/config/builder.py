from .schema import (
    AgentConfig,
    AgentPluginSettings,
    LockRetryConfig,
    ModelConfig,
    ProfileConfig,
    PromptConfig,
    ReadAfterWriteConfig,
    SendConfig,
    TargetConfig,
    TraceConfig,
    TriggerConfig,
    VisionConfig,
)
from .validation import validate_config

RECORDER_COMMAND_PREFIXES = ("recorder", "/recorder", "r", "/r")


def build_config(raw: dict) -> AgentPluginSettings:
    targets_data = raw.get("targets", {})
    trigger_data = raw.get("trigger", {})
    read_after_write_data = raw.get("read_after_write", {})
    agent_data = raw.get("agent", {})
    prompt_data = raw.get("prompt", {})
    profile_data = raw.get("profile", {})
    model_data = raw.get("model", {})
    send_data = raw.get("send", {})
    trace_data = raw.get("trace", {})
    lock_retry_data = raw.get("lock_retry", {})
    vision_data = raw.get("vision", {})

    settings = AgentPluginSettings(
        enabled=raw.get("enabled", False),
        recorder_db=str(raw.get("recorder_db", "") or ""),
        monitor_all=raw.get("monitor_all", False),
        targets=TargetConfig(
            groups=[str(item) for item in targets_data.get("groups", [])],
            private=[str(item) for item in targets_data.get("private", [])],
        ),
        trigger=TriggerConfig(
            private_enabled=trigger_data.get("private_enabled", True),
            group_enabled=trigger_data.get("group_enabled", True),
            prefixes=list(trigger_data.get("prefixes", ["/agent", "/ctx", "agent"])),
            allow_at=trigger_data.get("allow_at", True),
            allow_reply_to_bot=trigger_data.get("allow_reply_to_bot", False),
            ignore_self=trigger_data.get("ignore_self", True),
            ignore_recorder_command=trigger_data.get("ignore_recorder_command", True),
        ),
        read_after_write=ReadAfterWriteConfig(
            timeout_ms=read_after_write_data.get("timeout_ms", 320),
            backoff_ms=list(read_after_write_data.get("backoff_ms", [20, 40, 80, 160])),
        ),
        agent=AgentConfig(
            max_steps=agent_data.get("max_steps", 4),
            max_tool_calls_per_turn=agent_data.get("max_tool_calls_per_turn", 3),
            max_tool_calls_total=agent_data.get("max_tool_calls_total", 6),
            max_evidence_chars=agent_data.get("max_evidence_chars", 6000),
        ),
        prompt=PromptConfig(
            assistant_name=str(prompt_data.get("assistant_name", "Grok") or ""),
            system_template_path=str(
                prompt_data.get("system_template_path", "prompt/system.md") or ""
            ),
            context_message_preview_chars=prompt_data.get(
                "context_message_preview_chars", 280
            ),
        ),
        profile=ProfileConfig(
            db_path=str(profile_data.get("db_path", "data/profiles.json") or ""),
        ),
        model=ModelConfig(
            provider=model_data.get("provider", "ncatbot_ai"),
            model=model_data.get("model", ""),
            temperature=model_data.get("temperature", 0.5),
            max_tokens_group=model_data.get("max_tokens_group", 320),
            max_tokens_private=model_data.get("max_tokens_private", 520),
            timeout_sec=model_data.get("timeout_sec", 18),
            retries=model_data.get("retries", 1),
            llm_concurrency=model_data.get("llm_concurrency", 2),
            thinking_enabled=model_data.get("thinking_enabled", False),
            thinking_effort=model_data.get("thinking_effort", "high"),
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
            log_runtime=trace_data.get("log_runtime", True),
            log_context_blocks=trace_data.get("log_context_blocks", False),
            log_chars=trace_data.get("log_chars", 4000),
            pretty_print=trace_data.get("pretty_print", False),
            log_llm_chain=trace_data.get("log_llm_chain", False),
        ),
        lock_retry=LockRetryConfig(
            enabled=lock_retry_data.get("enabled", True),
            max_retries=lock_retry_data.get("max_retries", 5),
            base_delay_ms=lock_retry_data.get("base_delay_ms", 50),
        ),
        vision=VisionConfig(
            enabled=vision_data.get("enabled", False),
            dashscope_api_key=vision_data.get("dashscope_api_key", ""),
            image_fast_model=vision_data.get("image_fast_model", "qwen3-vl-flash"),
            image_detail_model=vision_data.get("image_detail_model", "qwen3-vl-plus"),
            image_deep_semantic_model=vision_data.get(
                "image_deep_semantic_model", "qwen3.7-plus"
            ),
            video_summary_model=vision_data.get("video_summary_model", "qwen3.6-flash"),
            temperature=vision_data.get("temperature", 0.4),
            timeout_sec=vision_data.get("timeout_sec", 20),
            source_image_bytes_threshold=vision_data.get(
                "source_image_bytes_threshold", 50 * 1024 * 1024
            ),
            api_image_bytes_max=vision_data.get(
                "api_image_bytes_max", 10 * 1024 * 1024
            ),
            max_images_per_message=vision_data.get("max_images_per_message", 3),
            include_in_context=vision_data.get("include_in_context", True),
            prompt_version=vision_data.get("prompt_version", "visual_v1"),
            schema_version=vision_data.get("schema_version", "visual_semantic_json_v1"),
            daily_limit_image_per_user_chat=vision_data.get(
                "daily_limit_image_per_user_chat", 30
            ),
            daily_limit_image_global=vision_data.get("daily_limit_image_global", 500),
            daily_limit_video_per_user_chat=vision_data.get(
                "daily_limit_video_per_user_chat", 3
            ),
            daily_limit_video_global=vision_data.get("daily_limit_video_global", 20),
            router_image_bytes_threshold=vision_data.get(
                "router_image_bytes_threshold", 1 * 1024 * 1024
            ),
            escalation_enabled=vision_data.get("escalation_enabled", True),
            escalation_min_confidence=vision_data.get(
                "escalation_min_confidence", 0.65
            ),
            escalation_max_images_escalate=vision_data.get(
                "escalation_max_images_escalate", 1
            ),
            escalation_detail_screenshot_types=vision_data.get(
                "escalation_detail_screenshot_types",
                ["screenshot", "document"],
            ),
            video_max_duration_min=vision_data.get("video_max_duration_min", 30),
            video_max_bytes=vision_data.get("video_max_bytes", 500 * 1024 * 1024),
            video_timeout_sec=vision_data.get("video_timeout_sec", 60),
        ),
    )
    validate_config(settings)
    return settings


def is_chat_targeted(
    chat_type: str,
    chat_id: str,
    settings: AgentPluginSettings,
) -> bool:
    if settings.monitor_all:
        return True
    if chat_type == "group":
        return chat_id in settings.targets.groups
    if chat_type == "private":
        return chat_id in settings.targets.private
    return False
