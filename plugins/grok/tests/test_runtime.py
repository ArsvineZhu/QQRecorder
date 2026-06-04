import asyncio
from types import SimpleNamespace

from plugins.grok.app.runtime import AgentRuntime
from plugins.grok.context.evidence import AgentStep, AgentToolCall


class _FakeRegistry:
    def __init__(self):
        self.calls = []

    def list_for_model(self):
        return []

    async def execute(self, name, arguments, context):
        self.calls.append((name, arguments, context))
        return {"status": "ok", "data": {"display_name": "Arsvine"}}


class _FakeAdapter:
    def __init__(self):
        self.calls = 0

    async def run(self, *, working_context, settings, registry, api):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                text="",
                tool_calls=[
                    AgentToolCall(
                        name="load_profile",
                        arguments={"user_id": "20001"},
                    )
                ],
                model_name="demo",
                request_summary="step1",
                response_summary="tool",
            )
        return SimpleNamespace(
            text="最终回复",
            tool_calls=[],
            model_name="demo",
            request_summary="step2",
            response_summary="final",
        )


def test_agent_runtime_executes_tool_then_returns_final_answer():
    async def _run():
        settings = SimpleNamespace(
            agent=SimpleNamespace(max_steps=3, max_tool_calls_per_turn=2),
            profile=SimpleNamespace(),
        )
        plugin = SimpleNamespace(
            settings=settings,
            api=SimpleNamespace(ai=object()),
            logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        )
        runtime = AgentRuntime(
            plugin,
            registry=_FakeRegistry(),
            model_runner=_FakeAdapter().run,
        )
        source_msg = SimpleNamespace(
            chat_type="group",
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="/agent 看看这个",
        )
        event = SimpleNamespace(
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="/agent 看看这个",
        )

        outcome = await runtime.run(
            event=event,
            source_msg=source_msg,
            trigger_reason="prefix:/agent",
        )

        assert outcome.text == "最终回复"
        assert outcome.error_code is None
        assert [step.tool_name for step in outcome.steps if step.kind == "tool"] == [
            "load_profile"
        ]
        assert any(
            block.kind == "tool_result" and block.label == "load_profile"
            for block in outcome.working_context.evidence
        )

    asyncio.run(_run())


def test_agent_step_summary_keeps_status_and_tool_name():
    step = AgentStep(kind="tool", tool_name="load_profile", status="ok", summary="done")

    assert step.kind == "tool"
    assert step.tool_name == "load_profile"
    assert step.status == "ok"
