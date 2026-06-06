from plugins.grok.shared.conversation_history import (
    build_transcript_turns,
    render_transcript_messages,
    trim_transcript_turns,
)


def test_build_transcript_turns_keeps_lightweight_turns_not_full_task_shell():
    turns = build_transcript_turns(
        source_message={
            "message_id": "evt-1",
            "timestamp": "2026-06-05 12:00:00",
            "raw_message": "@bot test",
            "chat_type": "group",
            "chat_id": "30001",
            "user_id": "20001",
            "sender": "Zodiac",
        },
        final_text="最终回复",
        messages_history=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "# 本轮回复任务\n\n不应该持久化这个壳"},
            {"role": "assistant", "content": "最终回复"},
        ],
    )

    assert turns == [
        {
            "type": "user",
            "content": "@bot test",
            "message_id": "evt-1",
            "timestamp": "2026-06-05 12:00:00",
            "sender": "Zodiac",
            "chat_type": "group",
            "chat_id": "30001",
            "user_id": "20001",
        },
        {"type": "assistant", "content": "最终回复"},
    ]


def test_render_transcript_messages_renders_group_sender_context():
    messages = render_transcript_messages(
        [
            {
                "type": "user",
                "content": "你们谁赢了",
                "message_id": "m-1",
                "timestamp": "2026-06-05 12:00:00",
                "sender": "Consciencieux",
                "chat_type": "group",
                "chat_id": "30001",
                "user_id": "20001",
            },
            {"type": "assistant", "content": "我觉得蓝方更稳。"},
        ]
    )

    assert messages[0]["role"] == "user"
    assert "Consciencieux" in messages[0]["content"]
    assert "你们谁赢了" in messages[0]["content"]
    assert messages[1] == {"role": "assistant", "content": "我觉得蓝方更稳。"}


def test_trim_transcript_turns_keeps_legal_user_boundary():
    turns = [
        {"type": "assistant", "content": "old"},
        {"type": "tool", "tool_call_id": "call-1", "content": "ignored"},
        {
            "type": "user",
            "content": "hello",
            "message_id": "m-1",
            "timestamp": "2026-06-05 12:00:00",
            "sender": "Z",
            "chat_type": "private",
            "chat_id": "20001",
            "user_id": "20001",
        },
        {"type": "assistant", "content": "hi"},
        {"type": "tool", "tool_call_id": "call-2", "content": "tool"},
    ]

    assert trim_transcript_turns(turns, max_messages=3) == [
        {
            "type": "user",
            "content": "hello",
            "message_id": "m-1",
            "timestamp": "2026-06-05 12:00:00",
            "sender": "Z",
            "chat_type": "private",
            "chat_id": "20001",
            "user_id": "20001",
        },
        {"type": "assistant", "content": "hi"},
        {"type": "tool", "tool_call_id": "call-2", "content": "tool"},
    ]
