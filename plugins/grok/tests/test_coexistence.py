from plugins.grok.config import build_config as build_agent_config
from plugins.grok.trigger import prefilter_event as agent_prefilter


class _FakeEvent:
    def __init__(self, raw_message: str):
        self.user_id = "20001"
        self.self_id = "10001"
        self.group_id = "30001"
        self.raw_message = raw_message
        self.message = None


def test_agent_plugin_defaults_ignore_non_agent_prefixes():
    agent_settings = build_agent_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "targets": {"groups": ["30001"]},
        }
    )

    non_agent_event = _FakeEvent("/ask 你好")
    agent_event = _FakeEvent("/agent 你好")

    assert agent_prefilter(non_agent_event, agent_settings) is None
    assert agent_prefilter(agent_event, agent_settings) == "prefix:/agent"
