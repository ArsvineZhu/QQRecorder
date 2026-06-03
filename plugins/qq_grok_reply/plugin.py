import logging
import os

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin

from .app.flow import handle_event
from .config import ReplyPluginSettings, build_config
from .infra import RecorderBridge, TraceStore
from .trigger import CooldownTracker


class QQGrokReplyPlugin(NcatBotPlugin):
    name = "qq_grok_reply"
    version = "1.0.0"
    author = "Arsvine Zhu"
    description = "基于 QQContextBot 的受控 AI 回复插件"

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

        logging.getLogger("LiteLLM").setLevel(logging.WARNING)

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

    async def _handle(self, event, chat_type: str) -> None:
        await handle_event(self, event, chat_type)
