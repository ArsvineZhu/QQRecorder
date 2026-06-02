import hashlib
import inspect
import os
import time
from typing import Any, cast

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray

from .config import ReplyPluginSettings, build_config
from .context_builder import build_context
from .model_client import ReplyModelError, generate_reply
from .recorder_bridge import RecorderBridge
from .sender import SendOutcome, send_reply
from .trace_store import TraceStore
from .trigger import CooldownTracker, final_decision, prefilter_event


class QQGrokReplyPlugin(NcatBotPlugin):
    name = "qq_grok_reply"
    version = "0.1.0"
    author = "Arsvine Zhu"
    description = "基于 QQRecorder 的受控 AI 回复插件"

    def __init__(self):
        super().__init__()
        self.settings: ReplyPluginSettings = build_config({})
        self._bridge: RecorderBridge | None = None
        self._trace_store: TraceStore | None = None
        self._cooldowns = CooldownTracker()

    async def on_load(self) -> None:
        self.settings = build_config(getattr(self, "config", {}) or {})
        if not self.settings.enabled:
            self.logger.info("qq_grok_reply loaded in disabled mode")
            return
        if not os.path.isabs(self.settings.recorder_db):
            raise ValueError("qq_grok_reply.recorder_db must be an absolute path")

        self._bridge = RecorderBridge()
        await self._bridge.connect_existing(self.settings.recorder_db)
        self._trace_store = TraceStore(self.settings.recorder_db)
        await self._trace_store.init_db()
        self.logger.info(
            "qq_grok_reply loaded | recorder_db=%s", self.settings.recorder_db
        )

    async def on_close(self) -> None:
        if self._bridge is not None:
            await self._bridge.close()
        if self._trace_store is not None:
            await self._trace_store.close()
        self.logger.info("qq_grok_reply unloaded")

    @registrar.qq.on_group_message()
    async def on_group_message(self, event: GroupMessageEvent) -> None:
        await self._handle(event, "group")

    @registrar.qq.on_private_message()
    async def on_private_message(self, event: PrivateMessageEvent) -> None:
        await self._handle(event, "private")

    async def _handle(self, event, _chat_type: str) -> None:
        prefilter_reason = prefilter_event(event, self.settings)
        if prefilter_reason is None:
            return

        bridge = self._require_bridge()
        trace_store = self._require_trace_store()
        started_at = time.perf_counter()
        source_msg = await bridge.wait_until_visible(
            str(event.message_id),
            timeout_ms=self.settings.read_after_write.timeout_ms,
            backoff_ms=self.settings.read_after_write.backoff_ms,
        )
        allowed, decision_reason = final_decision(
            event,
            source_msg=source_msg,
            prefilter_reason=prefilter_reason,
            settings=self.settings,
            cooldowns=self._cooldowns,
            bot_reply_message_ids=set(),
        )

        prompt_variant = (
            "group_compact"
            if getattr(event, "group_id", None) is not None
            else "private_contextual"
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
        ctx = await _resolve_awaitable(
            build_context(
                source_msg,
                bridge,
                self.settings,
                event=event,
                trigger_reason=decision_reason,
                sender_name=_sender_name(event),
            )
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
                context_ids=ctx.context_ids,
                prompt_variant=ctx.variant,
            )

        try:
            reply_text, meta = await _resolve_awaitable(
                generate_reply(self.api, ctx, self.settings)
            )
        except ReplyModelError as exc:
            fallback = await self._send_failure_fallback(event, decision_reason)
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
                )
            return

        outcome = await _resolve_awaitable(
            send_reply(self.api, event, reply_text, self.settings)
        )
        if trace_id is not None:
            await trace_store.finish_trace(
                trace_id,
                decision="replied" if outcome.sent else "error",
                model_name=meta["model_name"],
                model_request_summary=meta["model_request_summary"],
                model_response_summary=meta["model_response_summary"],
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                error_code=outcome.error_code,
                sent=outcome.sent,
                sent_message_id=outcome.sent_message_id,
                sent_parts=outcome.sent_parts,
            )

    def _require_bridge(self) -> RecorderBridge:
        if self._bridge is None:
            self._bridge = RecorderBridge()
        return self._bridge

    def _require_trace_store(self) -> TraceStore:
        if self._trace_store is None:
            self._trace_store = TraceStore(self.settings.recorder_db or ":memory:")
        return self._trace_store

    async def _send_failure_fallback(self, event, decision_reason: str) -> SendOutcome:
        is_group = getattr(event, "group_id", None) is not None
        should_send = not is_group or decision_reason.startswith("prefix:")
        if not should_send:
            return SendOutcome(False, None, 0, None)

        try:
            msg = (
                MessageArray()
                .add_text("我这边暂时没拿到模型结果，稍后再试一次。")
                .to_list()
            )
            qq_api = cast(Any, self.api.qq)
            if is_group:
                result = await qq_api.send_group_msg(str(event.group_id), msg)
            else:
                result = await qq_api.send_private_msg(str(event.user_id), msg)
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


async def _resolve_awaitable(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _sender_name(event) -> str:
    for field in ("card", "nickname", "sender_nickname", "user_name"):
        value = getattr(event, field, None)
        if value:
            return str(value)
    return str(getattr(event, "user_id", "") or "")
