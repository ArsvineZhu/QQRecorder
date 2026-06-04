import hashlib
import pprint
import time
from typing import Any, cast

from ncatbot.types import MessageArray

from ..config import RECORDER_COMMAND_PREFIXES, is_chat_targeted
from ..context import TopicContextError, build_context, expand_context
from ..delivery import SendOutcome, send_reply
from ..infra import RecorderBridge, TraceStore
from ..llm import ReplyGenerationResult, ReplyModelError, generate_reply
from ..shared import (
    chat_identity,
    json_list,
    json_payload,
    normalize_log_value,
    resolve_awaitable,
    sender_name,
)
from ..trigger import final_decision, prefilter_event
from .vision_bridge import VisionBridge


async def handle_event(plugin, event, chat_type: str) -> None:
    await PluginFlow(plugin).handle(event, chat_type)


class PluginFlow:
    def __init__(self, plugin) -> None:
        self.plugin = plugin
        self.settings = plugin.settings
        self.api = plugin.api
        self.logger = plugin.logger
        self._vision_bridge = VisionBridge(plugin)

    async def handle(self, event, _chat_type: str) -> None:  # noqa: C901
        event_message_id = str(getattr(event, "message_id", "") or "")
        prefilter_reason = prefilter_event(event, self.settings)
        if prefilter_reason is None and not self._may_be_reply_to_bot(event):
            return

        bridge = self._require_bridge()
        trace_store = self._require_trace_store()
        started_at = time.perf_counter()
        source_msg = await bridge.wait_until_visible(
            str(event.message_id),
            timeout_ms=self.settings.read_after_write.timeout_ms,
            backoff_ms=self.settings.read_after_write.backoff_ms,
        )
        bot_reply_message_ids = (
            await trace_store.get_sent_message_ids(
                *chat_identity(event, source_msg),
            )
            if prefilter_reason is None and self.settings.trigger.allow_reply_to_bot
            else set()
        )
        allowed, decision_reason = final_decision(
            event,
            source_msg=source_msg,
            prefilter_reason=prefilter_reason,
            settings=self.settings,
            cooldowns=self.plugin._cooldowns,
            bot_reply_message_ids=bot_reply_message_ids,
        )

        prompt_variant = (
            "group_topic_local"
            if getattr(event, "group_id", None) is not None
            else "private_topic_local"
        )
        self._log_runtime(
            "decision",
            message_id=event_message_id,
            chat_type="group"
            if getattr(event, "group_id", None) is not None
            else "private",
            chat_id=str(
                getattr(event, "group_id", None) or getattr(event, "user_id", "") or ""
            ),
            user_id=str(getattr(event, "user_id", "") or ""),
            source_visible=source_msg is not None,
            source_message_db_id=getattr(source_msg, "id", None),
            allowed=allowed,
            prefilter_reason=prefilter_reason or "",
            decision_reason=decision_reason,
        )
        if not allowed:
            if self.settings.trace.enabled:
                await trace_store.insert_trace(
                    source_message_id=str(event.message_id),
                    source_message_db_id=getattr(source_msg, "id", None),
                    chat_type="group"
                    if getattr(event, "group_id", None) is not None
                    else "private",
                    chat_id=str(
                        getattr(event, "group_id", None)
                        or getattr(event, "user_id", "")
                    ),
                    user_id=str(getattr(event, "user_id", "")),
                    decision_seed=self._decision_seed(event),
                    decision="error"
                    if decision_reason == "missing_recorder_row"
                    else "skipped",
                    trigger_reason=decision_reason,
                    context_ids=[str(event.message_id)],
                    prompt_variant=prompt_variant,
                )
            return

        assert source_msg is not None

        try:
            local_ctx = await resolve_awaitable(
                build_context(
                    source_msg,
                    bridge,
                    self.settings,
                    event=event,
                    trigger_reason=decision_reason,
                    sender_name=sender_name(event),
                    analyzer_api=self.api,
                    runtime_api=self.api,
                    visual_context="",
                )
            )
        except TopicContextError as exc:
            self._log_runtime(
                "topic_context_error",
                message_id=event_message_id,
                trigger_reason=decision_reason,
                error_code=exc.analysis.error_code,
                topic_title=exc.analysis.topic_title,
                topic_summary=exc.analysis.topic_summary,
                topic_confidence=exc.analysis.confidence,
                selected_ids=exc.analysis.selected_message_ids,
            )
            if self.settings.trace.enabled:
                analysis = exc.analysis
                await trace_store.insert_trace(
                    source_message_id=str(event.message_id),
                    source_message_db_id=getattr(source_msg, "id", None),
                    chat_type=str(source_msg.chat_type),
                    chat_id=str(
                        getattr(source_msg, "group_id", None) or source_msg.user_id
                    ),
                    user_id=str(source_msg.user_id),
                    decision_seed=self._decision_seed(event),
                    decision="error",
                    trigger_reason=decision_reason,
                    context_ids=[str(source_msg.message_id)],
                    prompt_variant=prompt_variant,
                    topic_title=analysis.topic_title,
                    topic_summary=analysis.topic_summary,
                    topic_participants_json=json_list(
                        [
                            f"{item.name}（{item.role}）" if item.role else item.name
                            for item in analysis.participants
                            if item.name
                        ]
                    ),
                    topic_selected_ids_json=json_list(analysis.selected_message_ids),
                    topic_candidate_count=analysis.candidate_count,
                    topic_confidence=analysis.confidence,
                    topic_error_code=analysis.error_code,
                    topic_fallback_used=False,
                )
            return
        local_ctx = await self._enrich_visual_context(source_msg, event, local_ctx)

        self._log_runtime(
            "context",
            message_id=event_message_id,
            trigger_reason=decision_reason,
            variant=local_ctx.variant,
            context_ids=local_ctx.context_ids,
            current_time=local_ctx.current_time,
            sender_name=local_ctx.sender_name,
            topic_title=local_ctx.topic_title,
            topic_summary=local_ctx.topic_summary,
            topic_confidence=local_ctx.topic_confidence,
            topic_candidate_count=local_ctx.topic_candidate_count,
            topic_error_code=local_ctx.topic_error_code,
            topic_fallback_used=local_ctx.topic_fallback_used,
            **self._context_log_payload(local_ctx),
        )
        trace_id = None
        if self.settings.trace.enabled:
            trace_id = await trace_store.insert_trace(
                source_message_id=str(event.message_id),
                source_message_db_id=getattr(source_msg, "id", None),
                chat_type=str(source_msg.chat_type),
                chat_id=str(
                    getattr(source_msg, "group_id", None) or source_msg.user_id
                ),
                user_id=str(source_msg.user_id),
                decision_seed=self._decision_seed(event),
                decision="pending",
                trigger_reason=decision_reason,
                context_ids=local_ctx.context_ids,
                prompt_variant=local_ctx.variant,
                topic_title=local_ctx.topic_title,
                topic_summary=local_ctx.topic_summary,
                topic_participants_json=json_list(local_ctx.topic_participants),
                topic_selected_ids_json=json_list(local_ctx.context_ids),
                topic_candidate_count=local_ctx.topic_candidate_count,
                topic_confidence=local_ctx.topic_confidence,
                topic_error_code=local_ctx.topic_error_code,
                topic_fallback_used=local_ctx.topic_fallback_used,
            )

        ctx = local_ctx
        topic_error_code = local_ctx.topic_error_code
        try:
            result = await resolve_awaitable(
                generate_reply(self.api, local_ctx, self.settings)
            )
        except ReplyModelError as exc:
            fallback = await self._send_failure_fallback(event, decision_reason)
            self._log_runtime(
                "llm_error",
                message_id=event_message_id,
                trigger_reason=decision_reason,
                error_code=exc.code,
                fallback_sent=fallback.sent,
                fallback_message_id=fallback.sent_message_id,
                fallback_parts=fallback.sent_parts,
                fallback_error_code=fallback.error_code,
            )
            if trace_id is not None:
                await trace_store.finish_trace(
                    trace_id,
                    decision="error",
                    model_name="",
                    model_request_summary="",
                    model_response_summary="",
                    latency_ms=int((time.perf_counter() - started_at) * 1000),
                    error_code=exc.code,
                    sent=fallback.sent,
                    sent_message_id=fallback.sent_message_id,
                    sent_parts=fallback.sent_parts,
                    topic_error_code=topic_error_code,
                )
            return

        result = self._coerce_generation_result(result)
        self._log_runtime(
            "llm_response",
            message_id=event_message_id,
            trigger_reason=decision_reason,
            model_name=result.model_name,
            response_text=result.text,
            request_summary=result.model_request_summary,
            response_summary=result.model_response_summary,
        )
        self._log_user_prompt(
            "llm_request_user_prompt",
            result.model_request_user_prompt,
        )

        if result.requested_more_context:
            self._log_runtime(
                "request_more_context",
                message_id=event_message_id,
                reason=result.request_reason,
                local_context_ids=local_ctx.context_ids,
            )
            try:
                ctx = await resolve_awaitable(
                    expand_context(
                        source_msg,
                        local_ctx,
                        bridge,
                        self.settings,
                        event=event,
                        trigger_reason=decision_reason,
                        sender_name=sender_name(event),
                        analyzer_api=self.api,
                        runtime_api=self.api,
                        request_reason=result.request_reason,
                    )
                )
            except TopicContextError as exc:
                topic_error_code = exc.analysis.error_code
                self._log_runtime(
                    "expand_context_error",
                    message_id=event_message_id,
                    trigger_reason=decision_reason,
                    error_code=topic_error_code,
                    request_reason=result.request_reason,
                )
                ctx = local_ctx
                if trace_id is not None:
                    await trace_store.update_trace_context(
                        trace_id,
                        context_ids=local_ctx.context_ids,
                        prompt_variant=local_ctx.variant,
                        topic_error_code=topic_error_code,
                    )
                if not self.settings.topic_analyzer.fallback_to_recent:
                    fallback = await self._send_failure_fallback(event, decision_reason)
                    self._log_runtime(
                        "expand_context_fallback_disabled",
                        message_id=event_message_id,
                        trigger_reason=decision_reason,
                        error_code=topic_error_code,
                        fallback_sent=fallback.sent,
                        fallback_message_id=fallback.sent_message_id,
                        fallback_parts=fallback.sent_parts,
                        fallback_error_code=fallback.error_code,
                    )
                    if trace_id is not None:
                        await trace_store.finish_trace(
                            trace_id,
                            decision="error",
                            model_name=result.model_name,
                            model_request_summary=result.model_request_summary,
                            model_response_summary=result.model_response_summary,
                            latency_ms=int((time.perf_counter() - started_at) * 1000),
                            error_code=fallback.error_code or topic_error_code,
                            sent=fallback.sent,
                            sent_message_id=fallback.sent_message_id,
                            sent_parts=fallback.sent_parts,
                            topic_error_code=topic_error_code,
                        )
                    return
            else:
                ctx = await self._enrich_visual_context(source_msg, event, ctx)
                topic_error_code = ctx.topic_error_code
                self._log_runtime(
                    "expanded_context",
                    message_id=event_message_id,
                    trigger_reason=decision_reason,
                    variant=ctx.variant,
                    context_ids=ctx.context_ids,
                    topic_title=ctx.topic_title,
                    topic_summary=ctx.topic_summary,
                    topic_confidence=ctx.topic_confidence,
                    topic_candidate_count=ctx.topic_candidate_count,
                    **self._context_log_payload(ctx),
                )
                if trace_id is not None:
                    await trace_store.update_trace_context(
                        trace_id,
                        context_ids=ctx.context_ids,
                        prompt_variant=ctx.variant,
                        topic_title=ctx.topic_title,
                        topic_summary=ctx.topic_summary,
                        topic_participants_json=json_list(ctx.topic_participants),
                        topic_selected_ids_json=json_list(ctx.context_ids),
                        topic_candidate_count=ctx.topic_candidate_count,
                        topic_confidence=ctx.topic_confidence,
                        topic_error_code=ctx.topic_error_code,
                        topic_fallback_used=ctx.topic_fallback_used,
                    )

            try:
                result = await resolve_awaitable(
                    generate_reply(
                        self.api, ctx, self.settings, allow_more_context=False
                    )
                )
                result = self._coerce_generation_result(result)
                self._log_runtime(
                    "llm_response_second_pass",
                    message_id=event_message_id,
                    trigger_reason=decision_reason,
                    model_name=result.model_name,
                    response_text=result.text,
                    request_summary=result.model_request_summary,
                    response_summary=result.model_response_summary,
                )
                self._log_user_prompt(
                    "llm_request_user_prompt_second_pass",
                    result.model_request_user_prompt,
                )
            except ReplyModelError as exc:
                fallback = await self._send_failure_fallback(event, decision_reason)
                self._log_runtime(
                    "llm_error_second_pass",
                    message_id=event_message_id,
                    trigger_reason=decision_reason,
                    error_code=exc.code,
                    fallback_sent=fallback.sent,
                    fallback_message_id=fallback.sent_message_id,
                    fallback_parts=fallback.sent_parts,
                    fallback_error_code=fallback.error_code,
                )
                if trace_id is not None:
                    await trace_store.finish_trace(
                        trace_id,
                        decision="error",
                        model_name="",
                        model_request_summary="",
                        model_response_summary="",
                        latency_ms=int((time.perf_counter() - started_at) * 1000),
                        error_code=exc.code,
                        sent=fallback.sent,
                        sent_message_id=fallback.sent_message_id,
                        sent_parts=fallback.sent_parts,
                        topic_error_code=topic_error_code,
                    )
                return

        outcome = await resolve_awaitable(
            send_reply(self.api, event, result.text, self.settings)
        )
        self._log_runtime(
            "send_result",
            message_id=event_message_id,
            sent=outcome.sent,
            sent_message_id=outcome.sent_message_id,
            sent_parts=outcome.sent_parts,
            error_code=outcome.error_code,
        )
        if trace_id is not None:
            await trace_store.finish_trace(
                trace_id,
                decision="replied" if outcome.sent else "error",
                model_name=result.model_name,
                model_request_summary=result.model_request_summary,
                model_response_summary=result.model_response_summary,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                error_code=outcome.error_code,
                sent=outcome.sent,
                sent_message_id=outcome.sent_message_id,
                sent_parts=outcome.sent_parts,
                topic_error_code=topic_error_code,
            )

    def _require_bridge(self) -> RecorderBridge:
        if self.plugin._bridge is None:
            self.plugin._bridge = RecorderBridge()
        return self.plugin._bridge

    def _require_trace_store(self) -> TraceStore:
        if self.plugin._trace_store is None:
            self.plugin._trace_store = TraceStore(
                self.settings.recorder_db or ":memory:"
            )
        return self.plugin._trace_store

    def _may_be_reply_to_bot(self, event) -> bool:
        if not self.settings.enabled or not self.settings.trigger.allow_reply_to_bot:
            return False

        user_id = str(getattr(event, "user_id", "") or "")
        self_id = str(getattr(event, "self_id", "") or "")
        if (
            self.settings.trigger.ignore_self
            and user_id
            and self_id
            and user_id == self_id
        ):
            return False

        raw_message = str(getattr(event, "raw_message", "") or "").strip()
        if (
            self.settings.trigger.ignore_recorder_command
            and raw_message
            and raw_message.split()[0].lower() in RECORDER_COMMAND_PREFIXES
        ):
            return False

        chat_type = "group" if getattr(event, "group_id", None) else "private"
        if chat_type == "group" and not self.settings.trigger.group_enabled:
            return False
        if chat_type == "private" and not self.settings.trigger.private_enabled:
            return False

        chat_id = str(
            getattr(event, "group_id", None) or getattr(event, "user_id", "") or ""
        )
        return bool(chat_id and is_chat_targeted(chat_type, chat_id, self.settings))

    async def _enrich_visual_context(self, source_msg, event, ctx):
        try:
            return await self._vision_bridge.enrich_context(source_msg, event, ctx)
        except Exception as exc:
            self.logger.warning("vision: failed to enrich context: %s", exc)
            return ctx

    async def _send_failure_fallback(self, event, decision_reason: str) -> SendOutcome:
        is_group = getattr(event, "group_id", None) is not None
        should_send = (
            not is_group
            or decision_reason.startswith("prefix:")
            or decision_reason in ("group_at_bot", "reply_to_bot")
        )
        if not should_send:
            return SendOutcome(False, None, 0, None)

        try:
            msg = MessageArray().add_text("我这边暂时没拿到模型结果，稍后再试一次。")
            qq_api = cast(Any, self.api.qq)
            if is_group:
                result = await qq_api.post_group_array_msg(str(event.group_id), msg)
            else:
                result = await qq_api.post_private_array_msg(str(event.user_id), msg)
            return SendOutcome(
                True,
                str(getattr(result, "message_id", "") or "") or None,
                1,
                None,
            )
        except Exception:
            return SendOutcome(False, None, 0, "send_error")

    @staticmethod
    def _decision_seed(event) -> str:
        key = f"{getattr(event, 'message_id', '')}:{getattr(event, 'time', '')}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]

    def _log_runtime(self, stage: str, **payload) -> None:
        if not self.settings.trace.log_runtime:
            return
        if self.settings.trace.pretty_print:
            normalized = {
                key: normalize_log_value(value, self.settings.trace.log_chars)
                for key, value in payload.items()
            }
            formatted = pprint.pformat(
                normalized, indent=2, sort_dicts=False, width=120
            )
            self.logger.info("qq_grok_reply %s |\n%s", stage, formatted)
        else:
            self.logger.info(
                "qq_grok_reply %s | %s",
                stage,
                json_payload(payload, self.settings.trace.log_chars),
            )

    def _context_log_payload(self, ctx) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "current_block_chars": len(ctx.current_block),
            "quoted_block_chars": len(ctx.quoted_block),
            "recent_block_chars": len(ctx.recent_block),
        }
        if self.settings.trace.log_context_blocks:
            payload.update(
                current_block=ctx.current_block,
                quoted_block=ctx.quoted_block,
                recent_block=ctx.recent_block,
            )
        return payload

    def _log_user_prompt(self, stage: str, prompt_text: str) -> None:
        if not self.settings.trace.log_runtime or not prompt_text:
            return
        self.logger.info("qq_grok_reply %s |\n%s", stage, prompt_text)

    @staticmethod
    def _coerce_generation_result(result) -> ReplyGenerationResult:
        if isinstance(result, ReplyGenerationResult):
            return result
        if isinstance(result, tuple) and len(result) == 2:
            text, meta = result
            meta = meta or {}
            return ReplyGenerationResult(
                text=str(text or ""),
                model_name=str(meta.get("model_name", "") or ""),
                model_request_summary=str(meta.get("model_request_summary", "") or ""),
                model_request_user_prompt=str(
                    meta.get("model_request_user_prompt", "") or ""
                ),
                model_response_summary=str(
                    meta.get("model_response_summary", "") or ""
                ),
            )
        raise TypeError("generate_reply returned unsupported result type")
