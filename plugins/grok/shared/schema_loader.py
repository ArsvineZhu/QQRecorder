from __future__ import annotations

import json
from pathlib import Path


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


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "schemas"
