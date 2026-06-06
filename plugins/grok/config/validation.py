import ntpath
import os

from .schema import AgentPluginSettings


def validate_config(settings: AgentPluginSettings) -> None:
    if (
        settings.enabled
        and settings.recorder_db
        and not _is_absolute_path(settings.recorder_db)
    ):
        raise ValueError("grok.recorder_db must be an absolute path")
    if settings.agent.max_steps <= 0:
        raise ValueError("agent.max_steps must be > 0")
    if settings.agent.max_tool_calls_per_turn <= 0:
        raise ValueError("agent.max_tool_calls_per_turn must be > 0")
    if settings.agent.max_tool_calls_total <= 0:
        raise ValueError("agent.max_tool_calls_total must be > 0")
    if settings.agent.max_tool_calls_total < settings.agent.max_tool_calls_per_turn:
        raise ValueError(
            "agent.max_tool_calls_total must be >= agent.max_tool_calls_per_turn"
        )
    if settings.agent.conversation_history_max_messages <= 0:
        raise ValueError("agent.conversation_history_max_messages must be > 0")
    if not str(settings.prompt.assistant_name or "").strip():
        raise ValueError("prompt.assistant_name must not be empty")
    if settings.prompt.context_message_preview_chars <= 0:
        raise ValueError("prompt.context_message_preview_chars must be > 0")
    if not settings.trigger.prefixes:
        raise ValueError("trigger.prefixes must not be empty")


def _is_absolute_path(value: str) -> bool:
    return os.path.isabs(value) or ntpath.isabs(value)
