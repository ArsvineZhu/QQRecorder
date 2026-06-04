from .config_schema import ReplyPluginSettings


def validate_config(settings: ReplyPluginSettings) -> None:
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
    if settings.context.mode not in {"topic_ai", "recent"}:
        raise ValueError("context.mode must be 'topic_ai' or 'recent'")
    _validate_context_limits(settings)
    _validate_topic_limits(settings)
    _validate_model_limits(settings)
    _validate_send_limits(settings)
    _validate_trace_limits(settings)
    _validate_lock_retry(settings)


def _validate_context_limits(settings: ReplyPluginSettings) -> None:
    if any(
        value <= 0
        for value in (
            settings.context.recent_limit_group,
            settings.context.recent_limit_private,
        )
    ):
        raise ValueError("context recent limits must be > 0")
    if any(
        value <= 0
        for value in (
            settings.context.quote_chars_group,
            settings.context.quote_chars_private,
        )
    ):
        raise ValueError("context quote limits must be > 0")
    if any(
        value <= 0
        for value in (
            settings.context.total_chars_group,
            settings.context.total_chars_private,
        )
    ):
        raise ValueError("context total limits must be > 0")


def _validate_model_limits(settings: ReplyPluginSettings) -> None:
    if settings.model.timeout_sec <= 0:
        raise ValueError("model.timeout_sec must be > 0")
    if settings.model.llm_concurrency <= 0:
        raise ValueError("model.llm_concurrency must be > 0")


def _validate_send_limits(settings: ReplyPluginSettings) -> None:
    if any(
        value <= 0
        for value in (
            settings.send.group_max_chars_per_part,
            settings.send.private_max_chars_per_part,
        )
    ):
        raise ValueError("send max chars must be > 0")
    if any(
        value <= 0
        for value in (
            settings.send.group_max_parts,
            settings.send.private_max_parts,
        )
    ):
        raise ValueError("send max parts must be > 0")


def _validate_trace_limits(settings: ReplyPluginSettings) -> None:
    if any(
        value <= 0
        for value in (
            settings.trace.preview_chars,
            settings.trace.log_chars,
        )
    ):
        raise ValueError("trace limits must be > 0")


def _validate_lock_retry(settings: ReplyPluginSettings) -> None:
    if settings.lock_retry.max_retries < 0 or settings.lock_retry.base_delay_ms <= 0:
        raise ValueError("lock_retry values are invalid")


def _validate_topic_limits(settings: ReplyPluginSettings) -> None:
    local_context_numbers = (
        settings.context.local_recent_limit_group,
        settings.context.local_recent_limit_private,
        settings.context.local_recent_time_window_minutes_group,
        settings.context.local_recent_time_window_minutes_private,
        settings.context.quote_chain_max_depth_group,
        settings.context.quote_chain_max_depth_private,
        settings.context.quote_neighbor_limit_group,
        settings.context.quote_neighbor_limit_private,
    )
    if any(value <= 0 for value in local_context_numbers):
        raise ValueError("local topic context limits must be > 0")

    context_numbers = (
        settings.context.candidate_limit_group,
        settings.context.candidate_limit_private,
        settings.context.candidate_time_window_minutes_group,
        settings.context.candidate_time_window_minutes_private,
        settings.context.selected_max_messages_group,
        settings.context.selected_max_messages_private,
        settings.context.forward_max_items,
        settings.context.forward_max_chars,
        settings.context.fallback_recent_limit_group,
        settings.context.fallback_recent_limit_private,
        settings.topic_analyzer.max_summary_chars,
    )
    if any(value <= 0 for value in context_numbers):
        raise ValueError("topic context limits must be > 0")
    if not 0 <= settings.topic_analyzer.min_confidence <= 1:
        raise ValueError("topic_analyzer.min_confidence must be between 0 and 1")
    if settings.topic_analyzer.timeout_sec <= 0:
        raise ValueError("topic_analyzer.timeout_sec must be > 0")


def _validate_targets(settings: ReplyPluginSettings) -> None:
    if not settings.enabled or settings.monitor_all:
        return

    for item in settings.targets.groups + settings.targets.private:
        if item and not str(item).isdigit():
            raise ValueError("target identifiers must contain only digits")
