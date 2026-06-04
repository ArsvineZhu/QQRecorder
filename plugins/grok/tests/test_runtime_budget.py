import asyncio
from types import SimpleNamespace

from plugins.grok.app.runtime import AgentRuntime
from plugins.grok.context.evidence import AgentToolCall


class _LargePayloadRegistry:
    def list_for_model(self):
        return []

    async def execute(self, name, arguments, context):
        del name, arguments, context
        return {"status": "ok", "data": {"payload": "x" * 500}}


class _SingleToolAdapter:
    def __init__(self):
        self.calls = 0

    async def run(self, *, working_context, settings, registry, api):
        del working_context, settings, registry, api
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                text="",
                tool_calls=[AgentToolCall(name="load_context", arguments={})],
                model_name="demo",
                request_summary="req",
                response_summary="tool",
            )
        return SimpleNamespace(
            text="done",
            tool_calls=[],
            model_name="demo",
            request_summary="req2",
            response_summary="done",
        )


def test_runtime_clips_large_evidence_payload_to_budget():
    async def _run():
        plugin = SimpleNamespace(
            settings=SimpleNamespace(
                agent=SimpleNamespace(
                    max_steps=3,
                    max_tool_calls_per_turn=1,
                    max_evidence_chars=120,
                )
            ),
            api=SimpleNamespace(ai=object()),
        )
        runtime = AgentRuntime(
            plugin,
            registry=_LargePayloadRegistry(),
            model_runner=_SingleToolAdapter().run,
        )
        source_msg = SimpleNamespace(
            chat_type="group",
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="/agent hi",
        )
        event = SimpleNamespace(
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="/agent hi",
        )

        outcome = await runtime.run(
            event=event,
            source_msg=source_msg,
            trigger_reason="prefix:/agent",
        )

        tool_result = next(
            block
            for block in outcome.working_context.evidence
            if block.kind == "tool_result"
        )
        assert len(tool_result.content) <= 120
        assert outcome.text == "done"

    asyncio.run(_run())
