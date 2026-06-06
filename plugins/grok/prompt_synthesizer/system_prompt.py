from __future__ import annotations

from pathlib import Path

from .renderers import assistant_name, sanitize_text
from .tool_prompt import render_tool_access_block


def render_system_prompt(settings, *, values: dict[str, str]) -> str:
    template_path = resolve_template_path(settings.prompt.system_template_path)
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    replacements = {
        "runtime_identity_block": build_runtime_identity_block(None),
        "assistant_name": assistant_name(settings),
        "tool_access_block": render_tool_access_block(),
    }
    replacements.update(values)
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_runtime_identity_block(context) -> str:
    bot_id = sanitize_text(str(getattr(context, "bot_id", "") or "unknown"))
    chat_id = sanitize_text(str(getattr(context, "chat_id", "") or "unknown"))
    user_id = sanitize_text(str(getattr(context, "user_id", "") or "unknown"))
    return "\n".join(
        [
            "## 运行时身份",
            "",
            f"- 你的 ID：`{bot_id}`",
            f"- 当前会话 ID：`{chat_id}`",
            f"- 当前发起用户 ID：`{user_id}`",
        ]
    )


def resolve_template_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent.parent / value
