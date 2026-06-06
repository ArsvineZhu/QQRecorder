from __future__ import annotations

from .renderers import sanitize_text
from .system_prompt import build_runtime_identity_block, render_system_prompt
from .user_task import build_user_content


def build_model_messages(
    working_context,
    settings,
    *,
    existing_messages: list[dict] | None = None,
) -> list[dict[str, str]]:
    if existing_messages is not None:
        return existing_messages
    system = render_system_prompt(
        settings,
        values={
            "runtime_identity_block": build_runtime_identity_block(
                working_context.context
            ),
        },
    )
    user = build_user_content(working_context, settings)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def render_working_context(working_context) -> str:
    context = working_context.context
    lines = [
        "# Working Context",
        "",
        "## Message To Answer",
        f"- User ID: `{context.user_id}`",
        f"- Content: {sanitize_text(context.current_message)}",
        "",
        "## Runtime Metadata",
        f"- Chat type: `{context.chat_type}`",
        f"- Chat ID: `{context.chat_id}`",
        f"- Bot ID: `{context.bot_id or 'unknown'}`",
        f"- Trigger: `{context.trigger_reason}`",
        f"- Parser: `{context.parser_version}`",
        f"- Context: `{context.context_version}`",
        f"- Profile: `{context.profile_version}`",
    ]
    if working_context.evidence:
        lines.extend(["", "## Evidence"])
    for block in working_context.evidence:
        lines.append(
            f"- `{block.kind}` / `{block.label}`: {sanitize_text(block.content)}"
        )
    return "\n".join(lines)
