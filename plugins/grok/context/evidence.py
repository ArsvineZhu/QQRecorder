from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceBlock:
    kind: str
    label: str
    content: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextBundle:
    chat_type: str
    chat_id: str
    user_id: str
    current_message: str
    trigger_reason: str
    bot_id: str = ""
    current_sender: str = ""
    current_time: str = ""
    group_instruction: str = ""
    parser_version: str = "v1"
    context_version: str = "v1"
    profile_version: str = "v1"


@dataclass
class AgentWorkingContext:
    context: ContextBundle
    evidence: list[EvidenceBlock] = field(default_factory=list)
    step_budget: int = 4
    tool_call_budget_total: int = 0
    tool_call_budget_remaining: int = 0
    replay_message_ids: set[str] = field(default_factory=set)
    llm_request_id: str = ""
    llm_step: int = 0
    source_message_id: str = ""


@dataclass
class AgentToolCall:
    name: str
    arguments: dict[str, Any]
    tool_call_id: str = ""


@dataclass
class AgentStep:
    kind: str
    tool_name: str
    status: str
    summary: str


@dataclass
class AgentOutcome:
    text: str
    working_context: AgentWorkingContext
    steps: list[AgentStep]
    model_name: str = ""
    error_code: str | None = None
    termination_reason: str | None = None
    messages_history: list[dict[str, Any]] | None = None
    transcript_turns: list[dict[str, Any]] | None = None
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
