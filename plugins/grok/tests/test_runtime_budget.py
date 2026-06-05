import asyncio
import json
from types import SimpleNamespace

from plugins.grok.agent.prompt import build_model_messages
from plugins.grok.app.runtime import AgentRuntime
from plugins.grok.config import build_config
from plugins.grok.context.evidence import AgentToolCall
from plugins.grok.tools.registry import ToolResponse


class _LargePayloadRegistry:
    def list_for_model(self):
        return []

    async def execute(self, name, arguments, context):
        del name, arguments, context
        return ToolResponse(status="ok", data={"payload": "x" * 500})


class _LargeContextRegistry:
    def list_for_model(self):
        return []

    async def execute(self, name, arguments, context):
        del arguments, context
        if name != "load_context":
            return ToolResponse(status="ok", data={})
        messages = []
        for index in range(8):
            messages.append(
                {
                    "message_id": f"m-{index}",
                    "user_id": "20001",
                    "sender_nickname": "Zodiac",
                    "sender_card": "",
                    "chat_type": "group",
                    "group_id": "30001",
                    "timestamp": f"2026-06-05 11:2{index}:00",
                    "raw_message": "这是一条很长的上下文消息 " + ("x" * 120),
                    "has_image": False,
                    "has_forward": False,
                }
            )
        return ToolResponse(status="ok", data={"messages": messages})


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
        assert '"status": "ok"' in tool_result.content
        assert outcome.text == "done"

    asyncio.run(_run())


def test_runtime_keeps_load_context_payload_as_valid_json_for_prompt_rendering():
    async def _run():
        plugin = SimpleNamespace(
            settings=SimpleNamespace(
                agent=SimpleNamespace(
                    max_steps=3,
                    max_tool_calls_per_turn=1,
                    max_evidence_chars=260,
                )
            ),
            api=SimpleNamespace(ai=object()),
        )
        runtime = AgentRuntime(
            plugin,
            registry=_LargeContextRegistry(),
            model_runner=_SingleToolAdapter().run,
        )
        source_msg = SimpleNamespace(
            chat_type="group",
            group_id="30001",
            user_id="20001",
            sender_nickname="Zodiac",
            message_id="evt-1",
            raw_message="/agent hi",
        )
        event = SimpleNamespace(
            group_id="30001",
            user_id="20001",
            self_id="10000",
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
            if block.kind == "tool_result" and block.label == "load_context"
        )
        payload = json.loads(tool_result.content)
        assert payload["status"] == "ok"
        assert payload["data"]["messages"]

        settings = build_config({"enabled": True, "recorder_db": "C:/tmp/recorder.db"})
        messages = build_model_messages(outcome.working_context, settings)
        assert "## 相关上下文" in messages[1]["content"]
        assert '{"status": "ok"' not in messages[1]["content"]
        assert "- `Zodiac`" in messages[1]["content"]

    asyncio.run(_run())


class _AlwaysToolAdapter:
    def __init__(self, tool_name="load_context", arguments=None):
        self.calls = 0
        self.tool_name = tool_name
        self.arguments = arguments or {}

    async def run(self, *, working_context, settings, registry, api):
        del working_context, settings, registry, api
        self.calls += 1
        return SimpleNamespace(
            text="",
            tool_calls=[AgentToolCall(name=self.tool_name, arguments=self.arguments)],
            model_name="demo",
            request_summary="req",
            response_summary="tool",
        )


class _SequencedToolAdapter:
    def __init__(self, sequence):
        self.calls = 0
        self.sequence = sequence

    async def run(self, *, working_context, settings, registry, api):
        del working_context, settings, registry, api
        item = self.sequence[self.calls]
        self.calls += 1
        if item["kind"] == "tool":
            return SimpleNamespace(
                text="",
                tool_calls=[
                    AgentToolCall(
                        name=item["name"],
                        arguments=item.get("arguments", {}),
                    )
                ],
                model_name="demo",
                request_summary=f"req-{self.calls}",
                response_summary=item["name"],
            )
        return SimpleNamespace(
            text=item["text"],
            tool_calls=[],
            model_name="demo",
            request_summary=f"req-{self.calls}",
            response_summary="final",
        )


def test_runtime_stops_at_global_tool_call_budget():
    async def _run():
        plugin = SimpleNamespace(
            settings=SimpleNamespace(
                agent=SimpleNamespace(
                    max_steps=4,
                    max_tool_calls_per_turn=1,
                    max_tool_calls_total=2,
                    max_evidence_chars=120,
                )
            ),
            api=SimpleNamespace(ai=object()),
        )
        registry = _LargePayloadRegistry()
        runtime = AgentRuntime(
            plugin,
            registry=registry,
            model_runner=_AlwaysToolAdapter().run,
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

        assert outcome.working_context.tool_call_budget_total == 2
        assert outcome.working_context.tool_call_budget_remaining == 0
        # Budget exceeded now skips extra tools and lets model continue
        # Since _AlwaysToolAdapter always returns tools, we hit max_steps
        assert outcome.error_code == "max_steps_exceeded"
        assert len([step for step in outcome.steps if step.status == "ok"]) == 2
        assert outcome.steps[-1].status == "skipped"
        payload = json.loads(outcome.steps[-1].summary)
        assert payload["error_code"] == "tool_budget_exceeded"
        assert payload["retryable"] is False

    asyncio.run(_run())


def test_runtime_skips_duplicate_track_reply_and_continues():
    async def _run():
        plugin = SimpleNamespace(
            settings=SimpleNamespace(
                agent=SimpleNamespace(
                    max_steps=4,
                    max_tool_calls_per_turn=1,
                    max_tool_calls_total=6,
                    max_evidence_chars=120,
                )
            ),
            api=SimpleNamespace(ai=object()),
        )
        registry = _LargePayloadRegistry()
        runtime = AgentRuntime(
            plugin,
            registry=registry,
            model_runner=_AlwaysToolAdapter("track_reply", {}).run,
        )
        source_msg = SimpleNamespace(
            chat_type="group",
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="[CQ:reply,id=old] 怎么回事",
        )
        event = SimpleNamespace(
            group_id="30001",
            user_id="20001",
            message_id="evt-1",
            raw_message="[CQ:reply,id=old] 怎么回事",
        )

        outcome = await runtime.run(
            event=event,
            source_msg=source_msg,
            trigger_reason="reply",
        )

        assert outcome.working_context.tool_call_budget_total == 6

        assert outcome.error_code == "max_steps_exceeded"
        assert len([step for step in outcome.steps if step.status == "ok"]) == 1
        assert outcome.steps[-1].status == "skipped"
        assert outcome.steps[-1].tool_name == "track_reply"
        payload = json.loads(outcome.steps[-1].summary)
        assert payload["status"] == "failed"
        assert payload["error_code"] == "duplicate_track_reply"
        assert payload["retryable"] is False

    asyncio.run(_run())


def test_runtime_does_not_charge_budget_for_load_tool_guide():
    async def _run():
        plugin = SimpleNamespace(
            settings=SimpleNamespace(
                agent=SimpleNamespace(
                    max_steps=4,
                    max_tool_calls_per_turn=1,
                    max_tool_calls_total=1,
                    max_evidence_chars=120,
                )
            ),
            api=SimpleNamespace(ai=object()),
        )
        registry = _LargePayloadRegistry()
        runtime = AgentRuntime(
            plugin,
            registry=registry,
            model_runner=_SequencedToolAdapter(
                [
                    {"kind": "tool", "name": "load_tool_guide", "arguments": {}},
                    {"kind": "tool", "name": "load_tool_guide", "arguments": {}},
                    {"kind": "tool", "name": "load_context", "arguments": {}},
                    {"kind": "final", "text": "done"},
                ]
            ).run,
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

        assert outcome.text == "done"
        assert outcome.working_context.tool_call_budget_total == 1
        assert outcome.working_context.tool_call_budget_remaining == 0
        assert [step.tool_name for step in outcome.steps if step.status == "ok"] == [
            "load_tool_guide",
            "load_tool_guide",
            "load_context",
        ]

    asyncio.run(_run())
