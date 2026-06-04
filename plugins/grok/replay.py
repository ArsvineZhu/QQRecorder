from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReplayCase:
    name: str
    event: object
    source_msg: object
    trigger_reason: str


@dataclass
class ReplayResult:
    case_name: str
    reply_text: str
    parser_version: str
    context_version: str
    profile_version: str
    error_code: str | None


async def run_replay_cases(
    *,
    runtime,
    cases: list[ReplayCase],
    parser_version: str,
    context_version: str,
    profile_version: str,
) -> list[ReplayResult]:
    results: list[ReplayResult] = []
    for case in cases:
        outcome = await runtime.run(
            event=case.event,
            source_msg=case.source_msg,
            trigger_reason=case.trigger_reason,
        )
        results.append(
            ReplayResult(
                case_name=case.name,
                reply_text=outcome.text,
                parser_version=parser_version,
                context_version=context_version,
                profile_version=profile_version,
                error_code=outcome.error_code,
            )
        )
    return results
