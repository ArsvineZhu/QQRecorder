from __future__ import annotations

from .context_blocks import append_runtime_context_sections, append_tool_budget_block
from .renderers import build_render_state, sanitize_text, semanticize_message_text


def build_user_content(working_context, settings) -> str:
    context = working_context.context
    sender = context.current_sender or context.user_id
    render_state = build_render_state(working_context, settings)
    current_message = semanticize_message_text(
        context.current_message,
        bot_id=str(context.bot_id or ""),
        id_to_name=render_state["id_to_name"],
        assistant_name=str(render_state["assistant_name"]),
    )
    parts = [
        "# 本轮回复任务",
        "",
        "## 要回答的用户消息",
        "",
        f"- 发送者：{sanitize_text(sender)}",
        f"- 用户 ID：`{sanitize_text(context.user_id)}`",
        f"- 触发原因：`{sanitize_text(context.trigger_reason)}`",
        "- 消息内容：",
        "",
        f"> {sanitize_text(current_message)}",
        "",
        "## 会话元信息",
        "",
        f"- 会话类型：`{sanitize_text(context.chat_type)}`",
        f"- 会话 ID：`{sanitize_text(context.chat_id)}`",
        f"- 自身 ID：`{sanitize_text(context.bot_id or 'unknown')}`",
        f"- 当前时间：`{sanitize_text(context.current_time or 'unknown')}`",
    ]
    append_runtime_context_sections(parts, working_context, render_state)
    append_tool_budget_block(parts, working_context)
    return "\n".join(parts)
