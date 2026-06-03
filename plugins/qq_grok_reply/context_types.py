from dataclasses import dataclass, field

from .topic_analyzer import TopicAnalysis


class TopicContextError(RuntimeError):
    def __init__(self, analysis: TopicAnalysis):
        super().__init__(analysis.error_code or "topic_context_error")
        self.analysis = analysis


@dataclass
class BuiltContext:
    context_ids: list[str]
    quoted_block: str
    recent_block: str
    current_block: str
    variant: str
    chat_type: str = ""
    trigger_reason: str = ""
    current_time: str = ""
    sender_name: str = ""
    max_reply_chars: int = 0
    topic_title: str = ""
    topic_summary: str = ""
    topic_participants: list[str] = field(default_factory=list)
    topic_confidence: float = 0.0
    topic_candidate_count: int = 0
    topic_error_code: str = ""
    topic_fallback_used: bool = False
    topic_excluded_ids_json: str = "[]"
