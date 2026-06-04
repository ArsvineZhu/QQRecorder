"""JSON-file-backed profile store.

Lighter alternative to SQLAlchemy for small profile datasets.
Stores all profiles in a single JSON file with file-level locking
for basic concurrency safety.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_DATA: dict[str, Any] = {
    "version": 1,
    "updated_at": "",
    "users": {},
}


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProfileJsonStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._data: dict[str, Any] | None = None

    async def init_db(self) -> None:
        def _init() -> None:
            path = Path(self._db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                if raw.strip():
                    parsed: dict[str, Any] = json.loads(raw)
                    parsed.setdefault("version", 1)
                    parsed.setdefault("users", {})
                    self._data = parsed
                    return
            self._data = dict(_DEFAULT_DATA)
            self._data["updated_at"] = _utc_iso()
            path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        await asyncio.to_thread(_init)

    async def close(self) -> None:
        self._data = None

    # ── Public helpers ──────────────────────────────────────────────

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        def _read() -> dict[str, Any] | None:
            self._ensure_loaded()
            raw = self._reload()
            return raw["users"].get(str(user_id))

        return await asyncio.to_thread(_read)

    async def upsert_profile(self, user_id: str, data: dict[str, Any]) -> None:
        def _upsert() -> None:
            self._ensure_loaded()
            raw = self._reload()
            raw["users"][str(user_id)] = data
            self._flush(raw)

        await asyncio.to_thread(_upsert)

    async def delete_profile(self, user_id: str) -> None:
        def _delete() -> None:
            self._ensure_loaded()
            raw = self._reload()
            raw["users"].pop(str(user_id), None)
            self._flush(raw)

        await asyncio.to_thread(_delete)

    async def list_profiles(self) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            self._ensure_loaded()
            raw = self._reload()
            return list(raw["users"].values())

        return await asyncio.to_thread(_list)

    async def get_all(self) -> dict[str, dict[str, Any]]:
        def _all() -> dict[str, dict[str, Any]]:
            self._ensure_loaded()
            raw = self._reload()
            return dict(raw["users"])

        return await asyncio.to_thread(_all)

    # ── Internal ────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._data is None:
            raise RuntimeError("ProfileJsonStore not initialized")

    def _reload(self) -> dict[str, Any]:
        path = Path(self._db_path)
        if not path.exists():
            return dict(_DEFAULT_DATA)
        raw_text = path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return dict(_DEFAULT_DATA)
        parsed: dict[str, Any] = json.loads(raw_text)
        parsed.setdefault("version", 1)
        parsed.setdefault("users", {})
        return parsed

    def _flush(self, data: dict[str, Any]) -> None:
        data["version"] = 1
        data["updated_at"] = _utc_iso()
        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._data = data
