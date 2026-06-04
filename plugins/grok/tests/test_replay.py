import asyncio
from types import SimpleNamespace

from plugins.grok.context.evidence import (
    AgentOutcome,
    AgentStep,
    AgentWorkingContext,
    ContextBundle,
)
from plugins.grok.replay import ReplayCase, run_replay_cases


class _FakeRuntime:
    async def run(self, *, event, source_msg, trigger_reason):
        del source_msg
        return AgentOutcome(
            text=f"reply:{event.raw_message}",
            working_context=AgentWorkingContext(
                context=ContextBundle(
                    chat_type="group",
                    chat_id="30001",
                    user_id="20001",
                    current_message=event.raw_message,
                    trigger_reason=trigger_reason,
                )
            ),
            steps=[
                AgentStep(
                    kind="tool",
                    tool_name="load_context",
                    status="ok",
                    summary="used",
                )
            ],
            model_name="demo",
            error_code=None,
        )


def test_run_replay_cases_returns_versioned_results():
    async def _run():
        case = ReplayCase(
            name="basic",
            event=SimpleNamespace(
                raw_message="/agent hi",
                group_id="30001",
                user_id="20001",
            ),
            source_msg=SimpleNamespace(
                chat_type="group",
                group_id="30001",
                user_id="20001",
                message_id="evt-1",
                raw_message="/agent hi",
            ),
            trigger_reason="prefix:/agent",
        )

        results = await run_replay_cases(
            runtime=_FakeRuntime(),
            cases=[case],
            parser_version="p1",
            context_version="c1",
            profile_version="u1",
        )

        assert results[0].case_name == "basic"
        assert results[0].reply_text == "reply:/agent hi"
        assert results[0].parser_version == "p1"
        assert results[0].context_version == "c1"
        assert results[0].profile_version == "u1"

    asyncio.run(_run())
