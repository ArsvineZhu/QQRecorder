from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_TOOL_METADATA = {
    "full_exposure": False,
    "counts_against_budget": True,
    "same_arguments_limit": "none",
}
_VALID_SAME_ARGUMENTS_LIMITS = {"none", "per_agent_run"}


def load_schema(relative_path: str) -> dict:
    target = _base_dir() / relative_path
    return json.loads(target.read_text(encoding="utf-8"))


def load_text_asset(relative_path: str) -> str:
    target = _base_dir() / relative_path
    return target.read_text(encoding="utf-8")


def load_tool_prompt_assets() -> tuple[dict, list[dict]]:
    tools_dir = _base_dir() / "tools"
    config_path = tools_dir / "_prompt_block.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    payloads: list[dict] = []
    for path in sorted(tools_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append({"name": path.stem, "schema": payload})
    return config, payloads


def load_tool_schema_map() -> dict[str, dict]:
    _, payloads = load_tool_prompt_assets()
    return {item["name"]: item["schema"] for item in payloads}


def load_tool_metadata(schema: dict[str, Any] | None) -> dict[str, Any]:
    raw = {}
    if isinstance(schema, dict):
        raw = schema.get("x-tool-meta", {}) or {}
    if not isinstance(raw, dict):
        raw = {}

    same_arguments_limit = str(
        raw.get(
            "same_arguments_limit",
            DEFAULT_TOOL_METADATA["same_arguments_limit"],
        )
        or DEFAULT_TOOL_METADATA["same_arguments_limit"]
    ).strip()
    if same_arguments_limit not in _VALID_SAME_ARGUMENTS_LIMITS:
        same_arguments_limit = DEFAULT_TOOL_METADATA["same_arguments_limit"]

    return {
        "full_exposure": bool(
            raw.get("full_exposure", DEFAULT_TOOL_METADATA["full_exposure"])
        ),
        "counts_against_budget": bool(
            raw.get(
                "counts_against_budget",
                DEFAULT_TOOL_METADATA["counts_against_budget"],
            )
        ),
        "same_arguments_limit": same_arguments_limit,
    }


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "schemas"
