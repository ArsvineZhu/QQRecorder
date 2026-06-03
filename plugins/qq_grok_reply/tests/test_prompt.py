from plugins.qq_grok_reply.llm.prompt import (
    PromptInput,
    build_messages,
)


def test_build_messages_uses_grok_like_system_prompt_and_group_speed():
    prompt_input = PromptInput(
        chat_type="group",
        current_time="2026-06-02 20:30",
        sender_name="Arsvine",
        quoted_block="",
        recent_block="[20:29] 20001: 最近消息",
        current_block="[20:30] Arsvine: 这个方案靠谱不？",
    )

    messages = build_messages(prompt_input)

    assert len(messages) == 2
    assert "AI 助手" in messages[0]["content"]
    assert "回复要短、快、有判断" in messages[0]["content"]
    assert "会话类型：group" in messages[1]["content"]
    assert "发送者：Arsvine" in messages[1]["content"]
    assert "【引用消息】" not in messages[1]["content"]


def test_build_messages_uses_private_speed():
    prompt_input = PromptInput(
        chat_type="private",
        current_time="2026-06-02 20:30",
        sender_name="20001",
        quoted_block="",
        recent_block="",
        current_block="[20:30] 20001: 你好",
    )

    messages = build_messages(prompt_input)

    assert "回复更完整，但仍然保持直接、有判断" in messages[0]["content"]
    assert "会话类型：private" in messages[1]["content"]
    assert "【当前消息】" in messages[1]["content"]
    assert "【引用消息】" not in messages[1]["content"]
    assert "【相关消息】" not in messages[1]["content"]


def test_build_messages_omits_empty_sections():
    prompt_input = PromptInput(
        chat_type="group",
        current_time="12:00",
        sender_name="User",
        quoted_block="",
        recent_block="",
        current_block="[12:00] User: 测试",
    )

    messages = build_messages(prompt_input)

    assert "【引用消息】" not in messages[1]["content"]
    assert "【相关消息】" not in messages[1]["content"]
    assert "【当前话题】" not in messages[1]["content"]
    assert "【会话信息】" in messages[1]["content"]
    assert "【当前消息】" in messages[1]["content"]


def test_build_messages_includes_sections_with_content():
    prompt_input = PromptInput(
        chat_type="group",
        current_time="12:00",
        sender_name="User",
        quoted_block="[11:59] Other: 引用内容",
        recent_block="[11:58] Someone: 最近消息",
        current_block="[12:00] User: 当前消息",
        topic_title="测试话题",
        topic_summary="这是摘要",
        topic_participants="User、Other",
        topic_confidence=0.85,
    )

    messages = build_messages(prompt_input)

    assert "【引用消息】" in messages[1]["content"]
    assert "【相关消息】" in messages[1]["content"]
    assert "【当前话题】" in messages[1]["content"]
    assert "测试话题" in messages[1]["content"]
    assert "【会话信息】" in messages[1]["content"]
    assert "【当前消息】" in messages[1]["content"]


def test_build_messages_omits_topic_section_when_empty():
    prompt_input = PromptInput(
        chat_type="group",
        current_time="12:00",
        sender_name="User",
        quoted_block="[11:59] Other: 引用",
        recent_block="[11:58] Someone: 最近",
        current_block="[12:00] User: 当前",
        topic_title="",
        topic_summary="",
        topic_participants="",
        topic_confidence=0.0,
    )

    messages = build_messages(prompt_input)

    assert "【当前话题】" not in messages[1]["content"]
    assert "【引用消息】" in messages[1]["content"]
    assert "【相关消息】" in messages[1]["content"]
