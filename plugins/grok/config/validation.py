import os

from .schema import AgentPluginSettings


def validate_config(settings: AgentPluginSettings) -> None:
    if (
        settings.enabled
        and settings.recorder_db
        and not os.path.isabs(settings.recorder_db)
    ):
        raise ValueError("grok.recorder_db must be an absolute path")
    if settings.agent.max_steps <= 0:
        raise ValueError("agent.max_steps must be > 0")
    if settings.agent.max_tool_calls_per_turn <= 0:
        raise ValueError("agent.max_tool_calls_per_turn must be > 0")
    if settings.agent.max_tool_calls_total <= 0:
        raise ValueError("agent.max_tool_calls_total must be > 0")
    if not settings.trigger.prefixes:
        raise ValueError("trigger.prefixes must not be empty")
