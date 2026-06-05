from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class ToolArgumentError(ValueError):
    pass


@dataclass
class ToolResponse:
    status: str
    data: dict[str, Any]
    message: str = ""
    error_code: str | None = None
    retryable: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def list_for_model(self) -> list[dict[str, Any]]:
        items = []
        for tool in self._tools.values():
            items.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": _sanitize_schema_for_model(tool.schema),
                    },
                }
            )
        return items

    def validate_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if name not in self._tools:
            raise ToolArgumentError(f"unknown tool: {name}")
        tool = self._tools[name]
        schema = tool.schema
        properties = schema.get("properties", {})
        self._validate_required(arguments, schema)
        self._validate_additional(arguments, properties, schema)
        self._validate_types(arguments, properties)
        return arguments

    @staticmethod
    def _validate_required(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
        required = set(schema.get("required", []))
        for required_name in required:
            if required_name not in arguments:
                raise ToolArgumentError(f"missing required argument: {required_name}")

    @staticmethod
    def _validate_additional(
        arguments: dict[str, Any],
        properties: dict[str, Any],
        schema: dict[str, Any],
    ) -> None:
        if schema.get("additionalProperties", True):
            return
        for key in arguments:
            if key not in properties:
                raise ToolArgumentError(f"unknown argument: {key}")

    @staticmethod
    def _validate_types(
        arguments: dict[str, Any],
        properties: dict[str, Any],
    ) -> None:
        for key, value in arguments.items():
            if key not in properties:
                continue
            expected = properties[key].get("type")
            if expected is None:
                continue
            expected_types = expected if isinstance(expected, list) else [expected]
            if not any(_matches_type(value, item) for item in expected_types):
                message = (
                    f"argument {key} expected type {expected_types} "
                    f"but got {type(value).__name__}"
                )
                raise ToolArgumentError(message)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> Any:
        validated = self.validate_tool_call(name, arguments)
        tool = self._tools[name]
        return await tool.handler(context, validated)


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


def _sanitize_schema_for_model(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key.startswith("x-"):
                continue
            sanitized[key] = _sanitize_schema_for_model(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_schema_for_model(item) for item in value]
    return value
