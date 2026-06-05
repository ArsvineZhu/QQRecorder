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


@dataclass
class AgentToolCall:
    name: str
    arguments: dict[str, Any]


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
