from __future__ import annotations

import json
from pathlib import Path


def load_schema(relative_path: str) -> dict:
    target = _base_dir() / relative_path
    return json.loads(target.read_text(encoding="utf-8"))


def load_text_asset(relative_path: str) -> str:
    target = _base_dir() / relative_path
    return target.read_text(encoding="utf-8")


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "schemas"
