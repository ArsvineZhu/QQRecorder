import asyncio
import json
from types import SimpleNamespace

from plugins.grok.app import orchestrator
from plugins.grok.context.evidence import (
    AgentOutcome,
    AgentWorkingContext,
    ContextBundle,
)


class _FakeTraceStore:
    def __init__(self):
        self.finished_context = None
        self.finished_trace = None

    async def get_sent_message_ids(self, chat_type, chat_id):
        del chat_type, chat_id
        return set()

    async def insert_trace(self, **kwargs):
        self.inserted = kwargs
        return 1

    async def finish_working_context(self, trace_id, working_context_json):
        assert trace_id == 1
        self.finished_context = json.loads(working_context_json)

    async def add_step(self, trace_id, step):
        del trace_id, step

    async def finish_trace(self, trace_id, **kwargs):
        assert trace_id == 1
        self.finished_trace = kwargs


def test_handle_event_skips_send_and_marks_trace_when_agent_terminates(monkeypatch):
    async def _run():
        monkeypatch.setattr(
            orchestrator,
            "prefilter_event",
            lambda event, settings: "ok",
        )
        monkeypatch.setattr(
            orchestrator,
            "final_decision",
            lambda event, **kwargs: (True, "group_at_bot"),
        )

        async def _unexpected_send_reply(api, event, text, settings):
            del api, event, text, settings
            raise AssertionError("send_reply should not be called for terminate")

        monkeypatch.setattr(orchestrator, "send_reply", _unexpected_send_reply)

        trace_store = _FakeTraceStore()
        source_msg = SimpleNamespace(
            chat_type="group",
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="@bot 这条先不用接",
            sender_card="",
            sender_nickname="Zodiac",
            timestamp="2026-06-05 12:00:00",
        )
        outcome = AgentOutcome(
            text="",
            working_context=AgentWorkingContext(
                context=ContextBundle(
                    chat_type="group",
                    chat_id="30001",
                    user_id="20001",
                    current_message="@bot 这条先不用接",
                    trigger_reason="group_at_bot",
                    bot_id="10000",
                )
            ),
            steps=[],
            model_name="demo",
            error_code="terminated_by_agent",
            termination_reason="群里现在不需要我插话",
        )
        plugin = SimpleNamespace(
            settings=SimpleNamespace(
                trigger=SimpleNamespace(allow_reply_to_bot=True),
                read_after_write=SimpleNamespace(timeout_ms=0, backoff_ms=0),
            ),
            _bridge=SimpleNamespace(
                wait_until_visible=lambda *args, **kwargs: asyncio.sleep(
                    0, result=source_msg
                )
            ),
            _trace_store=trace_store,
            _runtime=SimpleNamespace(
                run=lambda **kwargs: asyncio.sleep(0, result=outcome)
            ),
            _cooldowns=None,
            _profile_json_store=None,
            api=SimpleNamespace(),
        )
        event = SimpleNamespace(
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="@bot 这条先不用接",
            self_id="10000",
            time="2026-06-05 12:00:00",
        )

        await orchestrator.handle_event(plugin, event, "group")

        assert (
            trace_store.finished_context["termination_reason"] == "群里现在不需要我插话"
        )
        assert trace_store.finished_trace["response_text"] == ""
        assert trace_store.finished_trace["error_code"] == "terminated_by_agent"
        assert trace_store.finished_trace["sent"] is False

    asyncio.run(_run())
