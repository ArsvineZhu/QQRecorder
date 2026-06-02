import asyncio
from types import SimpleNamespace

from plugins.qq_grok_reply.config import build_config
from plugins.qq_grok_reply.topic_analyzer import analyze_topic


class _DictResponseAIAPI:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


def test_analyze_topic_accepts_openai_style_dict_response():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "monitor_all": True,
        }
    )
    api = SimpleNamespace(
        ai=_DictResponseAIAPI(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"topic_title":"存储","selected_message_ids":["m1"],'
                                '"confidence":0.8}'
                            )
                        }
                    }
                ]
            }
        )
    )

    analysis = asyncio.run(
        analyze_topic(
            api,
            payload={"current_message_id": "m1", "candidate_messages": []},
            settings=settings,
        )
    )

    assert analysis.error_code == ""
    assert analysis.topic_title == "存储"
    assert analysis.selected_message_ids == ["m1"]
    assert analysis.confidence == 0.8
