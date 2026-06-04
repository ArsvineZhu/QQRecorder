import asyncio

import pytest

from plugins.grok.tools.registry import (
    ToolArgumentError,
    ToolDefinition,
    ToolRegistry,
)


async def _echo_tool(_context, arguments):
    return {"status": "ok", "data": {"echo": arguments["query"]}}


def test_tool_registry_rejects_unknown_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="load_context",
            description="Load recent context for the current chat scope.",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=_echo_tool,
        )
    )

    with pytest.raises(ToolArgumentError, match="unknown argument"):
        registry.validate_tool_call("load_context", {"query": "topic", "extra": True})


def test_tool_registry_rejects_missing_required_argument():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="load_context",
            description="Load recent context for the current chat scope.",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=_echo_tool,
        )
    )

    with pytest.raises(ToolArgumentError, match="missing required argument"):
        registry.validate_tool_call("load_context", {"limit": 3})


def test_tool_registry_executes_registered_tool():
    async def _run():
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="load_context",
                description="Load recent context for the current chat scope.",
                schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                handler=_echo_tool,
            )
        )

        result = await registry.execute(
            "load_context",
            {"query": "topic", "limit": 5},
            context={"chat_type": "group", "chat_id": "30001"},
        )

        assert result["status"] == "ok"
        assert result["data"]["echo"] == "topic"

    asyncio.run(_run())
