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


class _TerminateRegistry:
    def list_for_model(self):
        return []

    async def execute(self, name, arguments, context):
        del context
        assert name == "terminate"
        return {
            "status": "ok",
            "data": {"terminated": True, "reason": arguments.get("reason", "")},
            "message": "terminated",
        }


class _TerminateAdapter:
    async def run(self, *, working_context, settings, registry, api):
        del working_context, settings, registry, api
        return SimpleNamespace(
            text="",
            tool_calls=[
                AgentToolCall(
                    name="terminate",
                    arguments={"reason": "群里现在不需要我插话"},
                )
            ],
            model_name="demo",
            request_summary="step1",
            response_summary="terminate",
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


def test_agent_runtime_returns_terminated_outcome_without_follow_up_reply():
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
            registry=_TerminateRegistry(),
            model_runner=_TerminateAdapter().run,
        )
        source_msg = SimpleNamespace(
            chat_type="group",
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="@bot 这条先不用接",
        )
        event = SimpleNamespace(
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="@bot 这条先不用接",
        )

        outcome = await runtime.run(
            event=event,
            source_msg=source_msg,
            trigger_reason="group_at_bot",
        )

        assert outcome.text == ""
        assert outcome.error_code == "terminated_by_agent"
        assert outcome.termination_reason == "群里现在不需要我插话"
        assert [step.tool_name for step in outcome.steps if step.kind == "tool"] == [
            "terminate"
        ]

    asyncio.run(_run())


def test_agent_step_summary_keeps_status_and_tool_name():
    step = AgentStep(kind="tool", tool_name="load_profile", status="ok", summary="done")

    assert step.kind == "tool"
    assert step.tool_name == "load_profile"
    assert step.status == "ok"


def test_agent_runtime_uses_configured_assistant_name_in_max_steps_fallback():
    async def _run():
        settings = SimpleNamespace(
            agent=SimpleNamespace(max_steps=1, max_tool_calls_per_turn=1),
            prompt=SimpleNamespace(assistant_name="博士"),
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
            model_runner=lambda **kwargs: asyncio.sleep(
                0,
                result=SimpleNamespace(
                    text="",
                    tool_calls=[AgentToolCall(name="load_profile", arguments={})],
                    model_name="demo",
                    request_summary="step1",
                    response_summary="tool",
                ),
            ),
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

        assert outcome.error_code == "max_steps_exceeded"
        assert outcome.text == "Agent 运行达到最大步数，博士.exe 已停止运行"

    asyncio.run(_run())
