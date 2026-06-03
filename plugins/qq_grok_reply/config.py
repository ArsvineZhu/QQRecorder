from .config_schema import (
    RECORDER_COMMAND_PREFIXES as _RECORDER_COMMAND_PREFIXES,
)
from .config_schema import (
    ContextConfig,
    CooldownConfig,
    LockRetryConfig,
    ModelConfig,
    ReadAfterWriteConfig,
    ReplyPluginSettings,
    SendConfig,
    TargetConfig,
    TopicAnalyzerConfig,
    TraceConfig,
    TriggerConfig,
)
from .config_validation import validate_config

RECORDER_COMMAND_PREFIXES = _RECORDER_COMMAND_PREFIXES


def build_config(raw: dict) -> ReplyPluginSettings:
    targets_data = raw.get("targets", {})
    trigger_data = raw.get("trigger", {})
    read_after_write_data = raw.get("read_after_write", {})
    context_data = raw.get("context", {})
    topic_analyzer_data = raw.get("topic_analyzer", {})
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
            mode=context_data.get("mode", "topic_ai"),
            recent_limit_group=context_data.get("recent_limit_group", 6),
            recent_limit_private=context_data.get("recent_limit_private", 10),
            local_recent_limit_group=context_data.get("local_recent_limit_group", 30),
            local_recent_limit_private=context_data.get(
                "local_recent_limit_private", 30
            ),
            local_recent_time_window_minutes_group=context_data.get(
                "local_recent_time_window_minutes_group", 30
            ),
            local_recent_time_window_minutes_private=context_data.get(
                "local_recent_time_window_minutes_private", 30
            ),
            quote_chain_max_depth_group=context_data.get(
                "quote_chain_max_depth_group", 10
            ),
            quote_chain_max_depth_private=context_data.get(
                "quote_chain_max_depth_private", 10
            ),
            quote_neighbor_limit_group=context_data.get(
                "quote_neighbor_limit_group", 10
            ),
            quote_neighbor_limit_private=context_data.get(
                "quote_neighbor_limit_private", 10
            ),
            quote_chars_group=context_data.get("quote_chars_group", 320),
            quote_chars_private=context_data.get("quote_chars_private", 480),
            total_chars_group=context_data.get("total_chars_group", 6000),
            total_chars_private=context_data.get("total_chars_private", 2200),
            recent_chars_group=context_data.get("recent_chars_group", 120),
            recent_chars_private=context_data.get("recent_chars_private", 180),
            candidate_limit_group=context_data.get("candidate_limit_group", 80),
            candidate_limit_private=context_data.get("candidate_limit_private", 30),
            candidate_time_window_minutes_group=context_data.get(
                "candidate_time_window_minutes_group", 45
            ),
            candidate_time_window_minutes_private=context_data.get(
                "candidate_time_window_minutes_private", 30
            ),
            selected_max_messages_group=context_data.get(
                "selected_max_messages_group", 20
            ),
            selected_max_messages_private=context_data.get(
                "selected_max_messages_private", 12
            ),
            forward_max_items=context_data.get("forward_max_items", 12),
            forward_max_chars=context_data.get("forward_max_chars", 1600),
            fallback_recent_limit_group=context_data.get(
                "fallback_recent_limit_group", 16
            ),
            fallback_recent_limit_private=context_data.get(
                "fallback_recent_limit_private", 12
            ),
        ),
        topic_analyzer=TopicAnalyzerConfig(
            enabled=topic_analyzer_data.get("enabled", True),
            model=topic_analyzer_data.get("model", ""),
            temperature=topic_analyzer_data.get("temperature", 0.2),
            timeout_sec=topic_analyzer_data.get("timeout_sec", 8),
            min_confidence=topic_analyzer_data.get("min_confidence", 0.45),
            fallback_to_recent=topic_analyzer_data.get("fallback_to_recent", True),
            max_summary_chars=topic_analyzer_data.get("max_summary_chars", 800),
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
            log_runtime=trace_data.get("log_runtime", True),
            log_context_blocks=trace_data.get("log_context_blocks", False),
            log_chars=trace_data.get("log_chars", 4000),
        ),
        lock_retry=LockRetryConfig(
            enabled=lock_retry_data.get("enabled", True),
            max_retries=lock_retry_data.get("max_retries", 5),
            base_delay_ms=lock_retry_data.get("base_delay_ms", 50),
        ),
    )
    validate_config(settings)
    return settings


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
