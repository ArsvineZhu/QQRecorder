import asyncio

from plugins.grok.infra import AgentConversationSessionStore


def test_conversation_session_store_round_trips_messages(tmp_path):
    async def _run():
        path = tmp_path / "grok.db"
        store = AgentConversationSessionStore(str(path))
        await store.init_db()
        messages = [
            {"role": "user", "content": "你好"},
            {
                "role": "assistant",
                "content": "在的",
                "reasoning_content": "用户在打招呼",
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
        ]

        await store.upsert_session("private", "20001", messages)
        loaded = await store.get_session("private", "20001")

        assert loaded == messages
        await store.close()

    asyncio.run(_run())


def test_conversation_session_store_isolated_by_chat_scope(tmp_path):
    async def _run():
        path = tmp_path / "grok.db"
        store = AgentConversationSessionStore(str(path))
        await store.init_db()
        await store.upsert_session(
            "group",
            "30001",
            [{"role": "user", "content": "群消息"}],
        )
        await store.upsert_session(
            "private",
            "20001",
            [{"role": "user", "content": "私聊消息"}],
        )

        assert await store.get_session("group", "30001") == [
            {"role": "user", "content": "群消息"}
        ]
        assert await store.get_session("private", "20001") == [
            {"role": "user", "content": "私聊消息"}
        ]
        assert await store.get_session("group", "99999") == []
        await store.close()

    asyncio.run(_run())


def test_conversation_session_store_recovers_from_concurrent_first_write(tmp_path):
    async def _run():
        path = tmp_path / "grok.db"
        store = AgentConversationSessionStore(str(path))
        await store.init_db()

        await asyncio.gather(
            store.upsert_session(
                "group",
                "30001",
                [{"type": "user", "content": "first"}],
            ),
            store.upsert_session(
                "group",
                "30001",
                [{"type": "user", "content": "second"}],
            ),
        )

        loaded = await store.get_session("group", "30001")
        await store.close()
        return loaded

    loaded = asyncio.run(_run())
    assert loaded in (
        [{"type": "user", "content": "first"}],
        [{"type": "user", "content": "second"}],
    )
