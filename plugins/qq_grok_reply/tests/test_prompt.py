from plugins.qq_grok_reply.prompt import (
    GROUP_MODE,
    PRIVATE_MODE,
    PromptInput,
    build_messages,
)


def test_build_messages_uses_grok_like_system_prompt_and_group_mode():
    prompt_input = PromptInput(
        chat_type="group",
        trigger_reason="prefix:/ask",
        current_time="2026-06-02 20:30",
        sender_name="Arsvine",
        quoted_block="无",
        recent_block="[20:29] 20001: 最近消息",
        current_block="[20:30] Arsvine: 这个方案靠谱不？",
        max_reply_chars=440,
    )

    messages = build_messages(prompt_input)

    assert len(messages) == 2
    assert "Grok-like 被动回复助手" in messages[0]["content"]
    assert GROUP_MODE in messages[0]["content"]
    assert "最大回复长度：\n440 字。" in messages[0]["content"]
    assert "触发原因：prefix:/ask" in messages[1]["content"]
    assert "发送者：Arsvine" in messages[1]["content"]


def test_build_messages_uses_private_mode():
    prompt_input = PromptInput(
        chat_type="private",
        trigger_reason="private",
        current_time="2026-06-02 20:30",
        sender_name="20001",
        quoted_block="无",
        recent_block="无",
        current_block="[20:30] 20001: 你好",
        max_reply_chars=1200,
    )

    messages = build_messages(prompt_input)

    assert PRIVATE_MODE in messages[0]["content"]
    assert "会话类型：private" in messages[1]["content"]
    assert "当前消息" in messages[1]["content"]
