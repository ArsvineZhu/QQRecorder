import asyncio

from plugins.grok.tools.profile_tools import load_profile


class _FakeStore:
    """Minimal in-memory store that mimics ProfileJsonStore."""

    def __init__(self, data: dict | None = None):
        self._data = data or {}

    async def get_profile(self, user_id: str) -> dict | None:
        return self._data.get(str(user_id))

    async def upsert_profile(self, user_id: str, data: dict) -> None:
        self._data[str(user_id)] = data


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
    assert "_status" in result.data


def test_load_profile_returns_username():
    store = _FakeStore({"40001": {"username": "Zodiac", "display_name": "Z"}})

    result = _run(
        load_profile(chat_type="group", chat_id="", user_id="40001", store=store)
    )
    assert result.data["username"] == "Zodiac"
