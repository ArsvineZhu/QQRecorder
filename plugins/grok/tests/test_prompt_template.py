from plugins.grok.agent.prompt import (
    build_model_messages,
    render_system_prompt,
)
from plugins.grok.config import build_config
from plugins.grok.context.evidence import AgentWorkingContext, ContextBundle


def test_render_system_prompt_uses_grok_template_text():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )

    rendered = render_system_prompt(
        settings,
        values={},
    )

    assert "AI 助手 Grok" in rendered
    assert "不要把聊天记录" in rendered
    assert "回复要短、快、有判断，适合插入群聊。" not in rendered


def test_build_model_messages_puts_scene_specific_instructions_in_user_context():
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
        )
    )

    messages = build_model_messages(working_context, settings)

    assert "回复要短、快、有判断" not in messages[0]["content"]
    assert "【回复要求】" in messages[1]["content"]
    assert "回复要短、快、有判断" in messages[1]["content"]
