import asyncio
import json

from plugins.grok.infra.profile_json_store import ProfileJsonStore
from plugins.grok.tools.profile_tools import load_profile


class _FakeStore:
    """Minimal in-memory store that mimics ProfileJsonStore."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}

    async def get_profile(self, user_id: str) -> dict | None:
        return self._data.get(str(user_id))

    async def upsert_profile(self, user_id: str, data: dict) -> None:
        self._data[str(user_id)] = data

    async def patch_profile(
        self,
        user_id: str,
        updates: dict,
        remove_keys: tuple[str, ...] = (),
    ) -> None:
        record = dict(self._data.get(str(user_id), {"user_id": str(user_id)}))
        record.update(updates)
        for key in remove_keys:
            record.pop(key, None)
        self._data[str(user_id)] = record

    async def delete_profile(self, user_id: str) -> None:
        self._data.pop(str(user_id), None)


def _run(coro):
    return asyncio.run(coro)


def test_load_profile_redacts_private_preferences_in_group_scope():
    store = _FakeStore(
        {
            "20001": {
                "display_name": "Arsvine",
                "preferred_name": "阿梓",
                "group_instruction": "技术问题先给结论",
                "private_instruction": "可以更直接，少铺垫",
                "language_style": "简洁直接",
                "habit_preferences": ["少客套", "喜欢例子"],
            }
        }
    )

    result = _run(
        load_profile(chat_type="group", chat_id="10001", user_id="20001", store=store)
    )

    assert result.status == "ok"
    assert result.data["preferred_name"] == "阿梓"
    assert result.data["group_instruction"] == "技术问题先给结论"
    assert "private_instruction" not in result.data
    assert result.data["habit_preferences"] == ["少客套", "喜欢例子"]


def test_load_profile_keeps_private_instruction_in_private_scope():
    store = _FakeStore(
        {
            "20001": {
                "display_name": "Arsvine",
                "preferred_name": "阿梓",
                "group_instruction": "技术问题先给结论",
                "private_instruction": "可以更直接，少铺垫",
                "language_style": "简洁直接",
                "habit_preferences": ["少客套", "喜欢例子"],
            }
        }
    )

    result = _run(
        load_profile(chat_type="private", chat_id="", user_id="20001", store=store)
    )

    assert result.status == "ok"
    assert result.data["private_instruction"] == "可以更直接，少铺垫"
    assert result.data["language_style"] == "简洁直接"


def test_load_profile_returns_group_nickname_for_correct_chat():
    store = _FakeStore(
        {
            "20001": {
                "username": "Arsvine",
                "group_nicknames": {"10001": "阿梓", "20002": "阿Z"},
            }
        }
    )

    result = _run(
        load_profile(chat_type="group", chat_id="10001", user_id="20001", store=store)
    )
    assert result.status == "ok"
    assert result.data["group_nickname"] == "阿梓"
    assert "username" in result.data


def test_load_profile_omits_wrong_chat_nickname():
    store = _FakeStore(
        {
            "20001": {
                "username": "Arsvine",
                "group_nicknames": {"10001": "阿梓"},
            }
        }
    )

    result = _run(
        load_profile(chat_type="group", chat_id="99999", user_id="20001", store=store)
    )
    assert result.status == "ok"
    assert "group_nickname" not in result.data
    assert result.data["username"] == "Arsvine"


def test_load_profile_auto_creates_new_user():
    store = _FakeStore()

    result = _run(
        load_profile(chat_type="private", chat_id="", user_id="30001", store=store)
    )
    assert result.status == "ok"
    assert result.data["username"] == "30001"
    assert result.data["group_instruction"]
    assert result.data["private_instruction"]


def test_load_profile_returns_username():
    store = _FakeStore({"40001": {"username": "Zodiac", "display_name": "Z"}})

    result = _run(
        load_profile(chat_type="group", chat_id="", user_id="40001", store=store)
    )
    assert result.data["username"] == "Zodiac"


def test_profile_json_store_preserves_concurrent_upserts(tmp_path):
    async def _run():
        path = tmp_path / "profiles.json"
        store = ProfileJsonStore(str(path))
        await store.init_db()

        await asyncio.gather(
            *(
                store.upsert_profile(str(index), {"user_id": str(index)})
                for index in range(30)
            )
        )

        all_profiles = await store.get_all()
        await store.close()

        assert set(all_profiles) == {str(index) for index in range(30)}
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert set(persisted["users"]) == {str(index) for index in range(30)}
        assert not path.with_suffix(path.suffix + ".tmp").exists()

    asyncio.run(_run())


def test_profile_json_store_patch_profile_merges_concurrent_updates(tmp_path):
    async def _run():
        path = tmp_path / "profiles.json"
        store = ProfileJsonStore(str(path))
        await store.init_db()
        await store.upsert_profile("u1", {"user_id": "u1"})

        await asyncio.gather(
            store.patch_profile("u1", {"username": "Arsvine"}),
            store.patch_profile("u1", {"language_style": "简洁直接"}),
        )

        profile = await store.get_profile("u1")
        await store.close()
        return profile

    profile = asyncio.run(_run())
    assert profile is not None
    assert profile["username"] == "Arsvine"
    assert profile["language_style"] == "简洁直接"


def test_profile_json_store_patch_profile_removes_requested_keys(tmp_path):
    async def _run():
        path = tmp_path / "profiles.json"
        store = ProfileJsonStore(str(path))
        await store.init_db()
        await store.upsert_profile(
            "u1",
            {
                "user_id": "u1",
                "username": "Arsvine",
                "muted_until": 123.0,
                "muted_group": "g1",
            },
        )

        await store.patch_profile("u1", {}, remove_keys=("muted_until", "muted_group"))
        profile = await store.get_profile("u1")
        await store.close()
        return profile

    profile = asyncio.run(_run())
    assert profile is not None
    assert profile["username"] == "Arsvine"
    assert "muted_until" not in profile
    assert "muted_group" not in profile


def test_profile_json_store_upsert_profile_replaces_existing_record(tmp_path):
    async def _run():
        path = tmp_path / "profiles.json"
        store = ProfileJsonStore(str(path))
        await store.init_db()
        await store.upsert_profile(
            "u1",
            {
                "user_id": "u1",
                "username": "Arsvine",
                "language_style": "简洁直接",
            },
        )
        await store.upsert_profile("u1", {"user_id": "u1", "username": "Zodiac"})
        profile = await store.get_profile("u1")
        await store.close()
        return profile

    profile = asyncio.run(_run())
    assert profile is not None
    assert profile["username"] == "Zodiac"
    assert "language_style" not in profile


def test_delete_profile_resets_profile_to_defaults_instead_of_removing_it():
    from types import SimpleNamespace

    from plugins.grok.tools.profile_tools import build_delete_profile_tool

    async def _run():
        store = _FakeStore(
            {
                "u1": {
                    "user_id": "u1",
                    "username": "Arsvine",
                    "preferred_name": "阿梓",
                    "group_instruction": "技术问题先给结论",
                    "private_instruction": "可以更直接，少铺垫",
                    "language_style": "简洁直接",
                    "habit_preferences": ["少客套"],
                    "group_nicknames": {"g1": "群名片"},
                }
            }
        )
        plugin = SimpleNamespace(_profile_json_store=store)
        tool = build_delete_profile_tool(plugin)

        result = await tool.handler(
            {
                "user_id": "u1",
                "chat_type": "group",
                "chat_id": "g1",
                "source_msg": SimpleNamespace(
                    sender_nickname="Arsvine",
                    sender_card="群名片",
                ),
            },
            {"user_id": "u1"},
        )

        profile = await store.get_profile("u1")
        return result, profile

    result, profile = asyncio.run(_run())
    assert result.status == "ok"
    assert result.message == "profile reset"
    assert profile is not None
    assert profile["user_id"] == "u1"
    assert profile["username"] == "Arsvine"
    assert profile["preferred_name"] == ""
    assert profile["language_style"] == ""
    assert profile["habit_preferences"] == []
    assert profile["group_nicknames"] == {"g1": "群名片"}
    assert profile["group_instruction"]
    assert profile["private_instruction"]
