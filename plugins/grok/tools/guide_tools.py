from __future__ import annotations

from typing import Any

from ..shared import load_schema, load_tool_metadata, load_tool_prompt_assets
from .registry import ToolDefinition, ToolResponse


def build_load_tool_guide_tool(plugin) -> ToolDefinition:
    del plugin

    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        del context
        tool_name = str(arguments.get("tool_name", "") or "").strip()
        config, payloads = load_tool_prompt_assets()
        payload_map = {item["name"]: item["schema"] for item in payloads}
        schema = payload_map.get(tool_name)
        if schema is None:
            return ToolResponse(
                status="failed",
                data={},
                error_code="unknown_tool_guide",
                message=f"unknown tool guide: {tool_name}",
                retryable=False,
            )

        return ToolResponse(
            status="ok",
            data=build_tool_guide_payload(
                tool_name,
                schema,
                guide_tool_name=str(
                    config.get("guide_tool_name", "load_tool_guide") or ""
                ),
            ),
        )

    return ToolDefinition(
        name="load_tool_guide",
        description=(
            "Load the full guide for a specific tool, including what it is for,"
            " how to use it, argument hints, and boundaries. Call this before"
            " using a tool when you are unsure."
        ),
        schema=load_schema("tools/load_tool_guide.json"),
        handler=_handler,
    )


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def build_tool_guide_payload(
    tool_name: str,
    schema: dict[str, Any],
    *,
    guide_tool_name: str,
) -> dict[str, Any]:
    meta = schema.get("x-prompt", {}) or {}
    policy = load_tool_metadata(schema)
    return {
        "tool_name": tool_name,
        "summary": str(
            meta.get("summary") or schema.get("description", "") or ""
        ).strip(),
        "usage": _string_list(meta.get("usage")),
        "guidance": _string_list(meta.get("guidance")),
        "boundaries": _string_list(meta.get("boundaries")),
        "arguments": _argument_descriptions(schema),
        "policy": policy,
        "policy_hints": _policy_hints(policy, guide_tool_name=guide_tool_name),
        "guide_tool_name": guide_tool_name,
    }


def _argument_descriptions(schema: dict[str, Any]) -> list[dict[str, Any]]:
    properties = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    items: list[dict[str, Any]] = []
    for name, payload in properties.items():
        if not isinstance(payload, dict):
            continue
        items.append(
            {
                "name": name,
                "required": name in required,
                "description": str(payload.get("description", "") or "").strip(),
            }
        )
    return items


def _policy_hints(
    policy: dict[str, Any],
    *,
    guide_tool_name: str,
) -> list[str]:
    hints = []
    if policy.get("full_exposure", False):
        hints.append("这是默认全量暴露给模型的特殊工具。")
    else:
        hints.append(
            f"默认只展示用途摘要；如果需要完整说明，再调用 `{guide_tool_name}`。"
        )
    if policy.get("counts_against_budget", True):
        hints.append("会消耗工具调用额度。")
    else:
        hints.append("不消耗工具调用额度。")
    if policy.get("same_arguments_limit") == "per_agent_run":
        hints.append("同一轮里不要用相同参数重复调用。")
    else:
        hints.append("同一轮里可以重复使用相同参数。")
    return hints
