from __future__ import annotations

from .renderers import render_evidence, render_group_roster


def append_section(parts: list[str], title: str, body: str) -> None:
    parts.extend(["", title])
    if not starts_with_subheading(body):
        parts.append("")
    parts.append(body)


def starts_with_subheading(body: str) -> bool:
    return str(body or "").lstrip().startswith("### ")


def append_runtime_context_sections(parts, working_context, render_state) -> None:
    roster = render_group_roster(render_state["roster"])
    if roster:
        parts.extend(["", "## 群聊档案", "", roster])

    quoted = render_evidence(
        working_context, {"track_reply"}, render_state=render_state
    )
    if quoted:
        append_section(parts, "## 引用消息", quoted)

    recent = render_evidence(
        working_context,
        {
            "load_context",
            "load_message",
            "extract_forward",
            "load_profile",
            "query_chat_history",
        },
        include_errors=True,
        render_state=render_state,
    )
    if recent:
        append_section(parts, "## 相关上下文", recent)

    visual = render_evidence(
        working_context,
        {"read_picture", "read_video"},
        render_state=render_state,
    )
    if visual:
        append_section(parts, "## 视觉分析", visual)


def append_tool_budget_block(parts: list[str], working_context) -> None:
    parts.extend(
        [
            "",
            "---",
            "",
            "## 工具数据",
            f"- 本轮工具总额度："
            f"`{int(getattr(working_context, 'tool_call_budget_total', 0) or 0)}`",
            f"- 当前剩余额度："
            f"`{int(getattr(working_context, 'tool_call_budget_remaining', 0) or 0)}`",
        ]
    )
