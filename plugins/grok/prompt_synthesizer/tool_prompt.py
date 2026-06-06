from __future__ import annotations

from typing import Any

from ..shared import load_tool_metadata, load_tool_prompt_assets
from ..tools.guide_tools import build_tool_guide_payload


def render_tool_access_block() -> str:
    config, payloads = load_tool_prompt_assets()
    guide_tool_name = str(config.get("guide_tool_name", "load_tool_guide") or "")
    payload_map = {item["name"]: item["schema"] for item in payloads}
    lines = ["## 工具说明访问规则", ""]
    intro = str(config.get("compact_intro", "") or "").strip()
    if intro:
        lines.append(intro)
    for item in config.get("compact_guidance", []) or []:
        text = str(item or "").strip()
        if text:
            lines.append(f"- {text}")
    if guide_tool_name:
        lines.append(
            "- 如果你准备使用某个工具，但不确定它的用法、边界或参数习惯，"
            f"先调用 `{guide_tool_name}`"
        )
    exposed_sections = _render_fully_exposed_tool_sections(
        config=config,
        payload_map=payload_map,
        guide_tool_name=guide_tool_name,
    )
    if exposed_sections:
        lines.extend(["", "## 特殊工具完整说明", "", exposed_sections])
    return "\n".join(line.rstrip() for line in lines).strip()


def _render_fully_exposed_tool_sections(
    *,
    config: dict[str, Any],
    payload_map: dict[str, dict[str, Any]],
    guide_tool_name: str,
) -> str:
    sections: list[str] = []
    for tool_name in config.get("tool_order", []) or []:
        schema = payload_map.get(str(tool_name))
        if schema is None:
            continue
        if not load_tool_metadata(schema).get("full_exposure", False):
            continue
        sections.append(
            _render_full_tool_section(
                build_tool_guide_payload(
                    str(tool_name),
                    schema,
                    guide_tool_name=guide_tool_name,
                )
            )
        )
    return "\n\n".join(section for section in sections if section.strip())


def _render_full_tool_section(payload: dict[str, Any]) -> str:
    lines = [f"## `{payload['tool_name']}`", "", payload["summary"]]
    arguments = payload.get("arguments", []) or []
    if arguments:
        lines.extend(["", "参数："])
        for item in arguments:
            marker = "必填" if item.get("required") else "可选"
            lines.append(
                f"- `{item.get('name', '')}`（{marker}）："
                f"{str(item.get('description', '') or '').strip()}"
            )
    for title, key in (
        ("适用场景：", "usage"),
        ("使用建议：", "guidance"),
        ("边界限制：", "boundaries"),
        ("策略说明：", "policy_hints"),
    ):
        values = payload.get(key, []) or []
        if not values:
            continue
        lines.extend(["", title])
        for item in values:
            lines.append(f"- {str(item).strip()}")
    return "\n".join(lines).strip()
