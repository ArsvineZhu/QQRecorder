from plugins.grok.agent.llm_chain_logger import (
    render_llm_chain_lines,
    validate_messages_for_chat_api,
)


def test_validate_messages_accepts_legal_tool_call_chain():
    diagnostics = validate_messages_for_chat_api(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "历史消息"},
            {"role": "user", "content": "# 本轮回复任务\n\n当前问题"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "load_context",
                            "arguments": '{"limit": 5}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
        ]
    )

    assert diagnostics == []


def test_validate_messages_reports_orphan_tool_and_missing_current_user():
    diagnostics = validate_messages_for_chat_api(
        [
            {"role": "system", "content": "system"},
            {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
        ]
    )

    codes = {item["code"] for item in diagnostics}
    assert "orphan_tool_message" in codes
    assert "missing_current_user_message" in codes


def test_render_llm_chain_lines_marks_current_and_tool_ids():
    lines = render_llm_chain_lines(
        request_id="req-1",
        chat_type="group",
        chat_id="30001",
        source_message_id="evt-1",
        step=2,
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "历史消息"},
            {"role": "user", "content": "# 本轮回复任务\n\n当前问题"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "load_context",
                            "arguments": '{"limit": 5}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
        ],
    )

    joined = "\n".join(lines)
    assert "source=current" in joined
    assert "tool_call_id=call-1" in joined
    assert "tool=load_context" in joined
