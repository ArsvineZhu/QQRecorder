"""JSON-file-backed profile store.

Lighter alternative to SQLAlchemy for small profile datasets.
Stores all profiles in a single JSON file with file-level locking
for basic concurrency safety.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

_DEFAULT_DATA: dict[str, Any] = {
    "version": 1,
    "updated_at": "",
    "users": {},
}


def _default_data() -> dict[str, Any]:
    return {"version": 1, "updated_at": "", "users": {}}


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProfileJsonStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._data: dict[str, Any] | None = None
        self._lock = Lock()

    async def init_db(self) -> None:
        def _init() -> None:
            with self._lock:
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
                self._data = _default_data()
                self._flush(self._data)

        await asyncio.to_thread(_init)

    async def close(self) -> None:
        def _close() -> None:
            with self._lock:
                self._data = None

        await asyncio.to_thread(_close)

    # ── Public helpers ──────────────────────────────────────────────

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        def _read() -> dict[str, Any] | None:
            with self._lock:
                self._ensure_loaded()
                raw = self._reload()
                value = raw["users"].get(str(user_id))
                return dict(value) if isinstance(value, dict) else value

        return await asyncio.to_thread(_read)

    async def upsert_profile(self, user_id: str, data: dict[str, Any]) -> None:
        def _upsert() -> None:
            with self._lock:
                self._ensure_loaded()
                raw = self._reload()
                record = dict(data)
                record["user_id"] = str(user_id)
                raw["users"][str(user_id)] = record
                self._flush(raw)

        await asyncio.to_thread(_upsert)

    async def patch_profile(
        self,
        user_id: str,
        updates: dict[str, Any],
        remove_keys: tuple[str, ...] = (),
        transform: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        def _patch() -> None:
            with self._lock:
                self._ensure_loaded()
                raw = self._reload()
                existing = raw["users"].get(str(user_id))
                if isinstance(existing, dict):
                    record = dict(existing)
                else:
                    record = {"user_id": str(user_id)}
                record.update(updates)
                for key in remove_keys:
                    record.pop(key, None)
                if transform is not None:
                    transform(record)
                record["user_id"] = str(user_id)
                raw["users"][str(user_id)] = record
                self._flush(raw)

        await asyncio.to_thread(_patch)

    async def delete_profile(self, user_id: str) -> None:
        def _delete() -> None:
            with self._lock:
                self._ensure_loaded()
                raw = self._reload()
                raw["users"].pop(str(user_id), None)
                self._flush(raw)

        await asyncio.to_thread(_delete)

    async def list_profiles(self) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            with self._lock:
                self._ensure_loaded()
                raw = self._reload()
                return [dict(item) for item in raw["users"].values()]

        return await asyncio.to_thread(_list)

    async def get_all(self) -> dict[str, dict[str, Any]]:
        def _all() -> dict[str, dict[str, Any]]:
            with self._lock:
                self._ensure_loaded()
                raw = self._reload()
                return {str(key): dict(value) for key, value in raw["users"].items()}

        return await asyncio.to_thread(_all)

    # ── Internal ────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._data is None:
            raise RuntimeError("ProfileJsonStore not initialized")

    def _reload(self) -> dict[str, Any]:
        path = Path(self._db_path)
        if not path.exists():
            return _default_data()
        raw_text = path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return _default_data()
        parsed: dict[str, Any] = json.loads(raw_text)
        parsed.setdefault("version", 1)
        parsed.setdefault("users", {})
        return parsed

    def _flush(self, data: dict[str, Any]) -> None:
        data["version"] = 1
        data["updated_at"] = _utc_iso()
        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        self._data = data
