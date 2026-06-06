from plugins.grok.agent import prompt as prompt_facade
from plugins.grok.config import build_config
from plugins.grok.context.evidence import AgentWorkingContext, ContextBundle
from plugins.grok.prompt_synthesizer import (
    build_model_messages,
    render_system_prompt,
    render_tool_access_block,
)


def test_prompt_synthesizer_exports_primary_prompt_entrypoints():
    assert callable(render_system_prompt)
    assert callable(render_tool_access_block)
    assert callable(build_model_messages)


def test_prompt_facade_keeps_backward_compatible_entrypoints():
    assert prompt_facade.render_system_prompt is render_system_prompt
    assert prompt_facade.render_tool_access_block is render_tool_access_block
    assert prompt_facade.build_model_messages is build_model_messages


def test_prompt_synthesizer_keeps_existing_rendering_behavior():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="30001",
            user_id="20001",
            current_message="看看这个",
            trigger_reason="prefix:/agent",
            bot_id="10000",
        )
    )

    messages = build_model_messages(working_context, settings)

    assert "你的 ID：`10000`" in messages[0]["content"]
    assert "# 本轮回复任务" in messages[1]["content"]
    assert "## 要回答的用户消息" in messages[1]["content"]
