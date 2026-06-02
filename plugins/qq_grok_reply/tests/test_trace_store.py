import asyncio
from pathlib import Path

from plugins.qq_grok_reply.trace_store import TraceStore


def test_trace_store_inserts_updates_and_deduplicates(tmp_path: Path):
    async def _run() -> None:
        db_path = tmp_path / "recorder.db"
        store = TraceStore(str(db_path))
        await store.init_db()

        trace_id = await store.insert_trace(
            source_message_id="m-1",
            source_message_db_id=11,
            chat_type="group",
            chat_id="30001",
            user_id="20001",
            decision_seed="seed-1",
            decision="skipped",
            trigger_reason="group_at_bot",
            context_ids=["m-1"],
            prompt_variant="group_compact",
            topic_title="硬盘选择",
            topic_summary="讨论硬盘容量",
            topic_participants_json='[{"name":"A"}]',
            topic_selected_ids_json='["m-1"]',
            topic_candidate_count=12,
            topic_confidence=0.75,
            topic_error_code="",
            topic_fallback_used=False,
        )
        duplicate_id = await store.insert_trace(
            source_message_id="m-1",
            source_message_db_id=11,
            chat_type="group",
            chat_id="30001",
            user_id="20001",
            decision_seed="seed-1",
            decision="skipped",
            trigger_reason="group_at_bot",
            context_ids=["m-1"],
            prompt_variant="group_compact",
        )
        assert duplicate_id == trace_id

        await store.finish_trace(
            trace_id,
            decision="replied",
            model_name="test-model",
            model_request_summary="request",
            model_response_summary="response",
            latency_ms=123,
            error_code=None,
            sent=True,
            sent_message_id="bot-1",
            sent_parts=2,
        )
        trace = await store.get_by_source_message_id("m-1")

        assert trace is not None
        assert trace.decision == "replied"
        assert trace.model_name == "test-model"
        assert trace.sent is True
        assert trace.sent_message_id == "bot-1"
        assert trace.sent_parts == 2
        assert trace.topic_title == "硬盘选择"
        assert trace.topic_candidate_count == 12
        assert trace.topic_confidence == 0.75
        assert trace.topic_fallback_used is False
        assert await store.get_sent_message_ids("group", "30001") == {"bot-1"}
        assert await store.get_sent_message_ids("private", "20001") == set()

        await store.close()

    asyncio.run(_run())
