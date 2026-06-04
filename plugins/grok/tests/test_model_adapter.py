import asyncio
from types import SimpleNamespace

from plugins.grok.agent.model_adapter import run_agent_turn
from plugins.grok.config import build_config
from plugins.grok.context.evidence import AgentWorkingContext, ContextBundle
from plugins.grok.tools.registry import ToolDefinition, ToolRegistry


class _FakeAIAPI:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


async def _noop_tool(_context, arguments):
    return {"status": "ok", "data": arguments}


def _working_context():
    return AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="30001",
            user_id="20001",
            current_message="看看这个",
            trigger_reason="prefix:/agent",
        ),
        evidence=[],
        step_budget=4,
    )


def test_run_agent_turn_parses_tool_calls():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="load_profile",
            description="Load the calling user's conversation preferences.",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
            handler=_noop_tool,
        )
    )
    settings = build_config({"enabled": True, "recorder_db": "C:/tmp/recorder.db"})
    api = SimpleNamespace(
        ai=_FakeAIAPI(
            response=SimpleNamespace(
                model="demo",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="load_profile",
                                        arguments='{"user_id":"20001"}',
                                    )
                                )
                            ]
                        )
                    )
                ],
            )
        )
    )

    result = asyncio.run(
        run_agent_turn(
            api=api,
            working_context=_working_context(),
            settings=settings,
            registry=registry,
        )
    )

    assert result.text == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "load_profile"
    assert result.tool_calls[0].arguments == {"user_id": "20001"}
    assert "tools" in api.ai.calls[0][1]
    messages = api.ai.calls[0][0]
    assert "AI 助手 Grok" in messages[0]["content"]
    assert "回复要短、快、有判断" not in messages[0]["content"]
    assert "【会话信息】" in messages[1]["content"]
    assert "【回复要求】" in messages[1]["content"]
    assert "【当前消息】" in messages[1]["content"]


def test_run_agent_turn_returns_final_text_without_tool_call():
    registry = ToolRegistry()
    settings = build_config({"enabled": True, "recorder_db": "C:/tmp/recorder.db"})
    api = SimpleNamespace(
        ai=_FakeAIAPI(
            response=SimpleNamespace(
                model="demo",
                choices=[SimpleNamespace(message=SimpleNamespace(content="直接回答"))],
            )
        )
    )

    result = asyncio.run(
        run_agent_turn(
            api=api,
            working_context=_working_context(),
            settings=settings,
            registry=registry,
        )
    )

    assert result.text == "直接回答"
    assert result.tool_calls == []
