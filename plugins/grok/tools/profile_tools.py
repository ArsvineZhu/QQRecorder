from __future__ import annotations

from typing import Any

from ..profile_defaults import build_default_profile
from ..shared import load_schema
from .registry import ToolDefinition, ToolResponse


def _strip_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in ("", [], None)}


def _convert_prefs(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [s.strip() for s in raw if isinstance(s, str) and s.strip()]
    if raw and isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []


async def load_profile(
    *,
    chat_type: str,
    chat_id: str,
    user_id: str,
    store,
    sender_nickname: str = "",
    sender_card: str = "",
) -> ToolResponse:
    """Load profile from JSON store, auto-create if new user."""
    if store is None:
        return ToolResponse(status="ok", data={})
    data = await store.get_profile(user_id)
    if data is None:
        record = build_default_profile(
            user_id=user_id,
            chat_type=chat_type,
            chat_id=chat_id,
            sender_nickname=sender_nickname,
            sender_card=sender_card,
        )
        await store.upsert_profile(user_id, record)
        data = record

    safe: dict[str, Any] = {}
    for key in (
        "username",
        "preferred_name",
        "group_instruction",
        "language_style",
        "habit_preferences",
    ):
        if data.get(key):
            safe[key] = data[key]

    if not safe:
        safe["_status"] = "档案已存在，无额外信息"

    # Resolve per-group nickname
    raw_nicknames: Any = data.get("group_nicknames", {})
    group_nicknames = raw_nicknames if isinstance(raw_nicknames, dict) else {}
    if chat_type == "group" and chat_id and group_nicknames.get(chat_id):
        nick: Any = group_nicknames[chat_id]
        if isinstance(nick, str):
            safe["group_nickname"] = nick

    # Private instruction only in private scope
    if chat_type == "private" and data.get("private_instruction"):
        safe["private_instruction"] = data["private_instruction"]

    return ToolResponse(
        status="ok",
        data=_strip_none(safe),
        meta={"scope": chat_type},
    )


def build_load_profile_tool(plugin) -> ToolDefinition:
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        chat_type = str(context.get("chat_type") or "")
        chat_id = str(context.get("chat_id") or "")
        user_id = str(arguments.get("user_id") or context.get("user_id") or "")
        source_msg = context.get("source_msg")
        store = getattr(plugin, "_profile_json_store", None)
        return await load_profile(
            chat_type=chat_type,
            chat_id=chat_id,
            user_id=user_id,
            store=store,
            sender_nickname=str(
                getattr(source_msg, "sender_nickname", "")
                or getattr(source_msg, "sender_card", "")
                or ""
            ),
            sender_card=str(getattr(source_msg, "sender_card", "") or ""),
        )

    return ToolDefinition(
        name="load_profile",
        description=(
            "Load the current user's profile defaults and personalized preferences."
        ),
        schema=load_schema("tools/load_profile.json"),
        handler=_handler,
    )


# ── shared helpers for create/update ──────────────────────────────


def _apply_common_fields(record: dict[str, Any], arguments: dict[str, Any]) -> None:
    for field in (
        "username",
        "preferred_name",
        "group_instruction",
        "private_instruction",
        "language_style",
    ):
        val = arguments.get(field)
        if val is not None and str(val).strip():
            record[field] = str(val).strip()

    raw_prefs = arguments.get("habit_preferences")
    if raw_prefs is not None:
        prefs = _convert_prefs(raw_prefs)
        if prefs:
            record["habit_preferences"] = prefs


def _apply_group_nickname(record: dict[str, Any], raw_nick: Any, chat_id: str) -> None:
    """Update per-group nickname in ``record["group_nicknames"]``."""
    if not chat_id:
        return
    group_nicknames = record.get("group_nicknames", {}) or {}
    if str(raw_nick).strip():
        group_nicknames[chat_id] = str(raw_nick).strip()
    else:
        group_nicknames.pop(chat_id, None)
    record["group_nicknames"] = group_nicknames


def build_create_profile_tool(plugin) -> ToolDefinition:
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        user_id = str(arguments.get("user_id") or context.get("user_id") or "")
        if not user_id:
            return ToolResponse(
                status="failed",
                data={},
                error_code="missing_user_id",
                message="user_id is required",
            )
        store = getattr(plugin, "_profile_json_store", None)
        if store is None:
            return ToolResponse(
                status="failed", data={}, error_code="store_unavailable"
            )
        existing = await store.get_profile(user_id)
        if existing is not None:
            safe = {k: v for k, v in existing.items() if k != "user_id"}
            return ToolResponse(
                status="ok", data=_strip_none(safe), message="profile already exists"
            )
        record: dict[str, Any] = {"user_id": user_id}
        _apply_common_fields(record, arguments)
        raw_nick = arguments.get("group_nickname")
        if raw_nick is not None:
            _apply_group_nickname(record, raw_nick, context.get("chat_id", ""))
        await store.upsert_profile(user_id, record)
        safe = {k: v for k, v in record.items() if k != "user_id"}
        return ToolResponse(
            status="ok", data=_strip_none(safe), message="profile created"
        )

    return ToolDefinition(
        name="create_profile",
        description=(
            "Create an empty profile for a new user,"
            " optionally with initial preferences."
        ),
        schema=load_schema("tools/create_profile.json"),
        handler=_handler,
    )


def build_update_profile_tool(plugin) -> ToolDefinition:
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        user_id = str(arguments.get("user_id") or context.get("user_id") or "")
        if not user_id:
            return ToolResponse(
                status="failed",
                data={},
                error_code="missing_user_id",
                message="user_id is required",
            )
        store = getattr(plugin, "_profile_json_store", None)
        if store is None:
            return ToolResponse(
                status="failed", data={}, error_code="store_unavailable"
            )
        updates: dict[str, Any] = {}
        _apply_common_fields(updates, arguments)
        raw_nick = arguments.get("group_nickname")
        transform = None
        if raw_nick is not None:
            chat_id = str(context.get("chat_id", "") or "")

            def _transform(record: dict[str, Any]) -> None:
                _apply_group_nickname(record, raw_nick, chat_id)

            transform = _transform
        await store.patch_profile(user_id, updates, transform=transform)
        updated_fields = [
            k for k in arguments if k != "user_id" and arguments[k] is not None
        ]
        return ToolResponse(
            status="ok",
            data={"updated": updated_fields},
            message="profile updated",
        )

    return ToolDefinition(
        name="update_profile",
        description=(
            "Update specific fields in the caller's profile."
            " Unpassed fields are kept unchanged."
        ),
        schema=load_schema("tools/update_profile.json"),
        handler=_handler,
    )


def build_delete_profile_tool(plugin) -> ToolDefinition:
    async def _handler(
        context: dict[str, Any],
        arguments: dict[str, Any],
    ) -> ToolResponse:
        user_id = str(arguments.get("user_id") or context.get("user_id") or "")
        if not user_id:
            return ToolResponse(
                status="failed",
                data={},
                error_code="missing_user_id",
                message="user_id is required",
            )
        store = getattr(plugin, "_profile_json_store", None)
        if store is None:
            return ToolResponse(
                status="failed", data={}, error_code="store_unavailable"
            )
        source_msg = context.get("source_msg")
        chat_type = str(context.get("chat_type") or "")
        chat_id = str(context.get("chat_id") or "")
        record = build_default_profile(
            user_id=user_id,
            chat_type=chat_type,
            chat_id=chat_id,
            sender_nickname=str(
                getattr(source_msg, "sender_nickname", "")
                or getattr(source_msg, "sender_card", "")
                or ""
            ),
            sender_card=str(getattr(source_msg, "sender_card", "") or ""),
        )
        await store.upsert_profile(user_id, record)
        return ToolResponse(status="ok", data={}, message="profile reset")

    return ToolDefinition(
        name="delete_profile",
        description="Reset the current user's profile back to its default state.",
        schema=load_schema("tools/delete_profile.json"),
        handler=_handler,
    )
