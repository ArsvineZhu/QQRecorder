from __future__ import annotations

from ..shared import load_schema
from .registry import ToolDefinition, ToolResponse


def build_terminate_tool(plugin) -> ToolDefinition:
    del plugin

    async def _handler(context, arguments):
        del context
        reason = str(arguments.get("reason", "") or "").strip()
        return ToolResponse(
            status="ok",
            data={"terminated": True, "reason": reason},
            message="terminate requested",
            meta={"control": "terminate"},
        )

    return ToolDefinition(
        name="terminate",
        description=(
            "End the current agent run without sending any chat reply when the"
            " best action is to stay silent."
        ),
        schema=load_schema("tools/terminate.json"),
        handler=_handler,
    )
