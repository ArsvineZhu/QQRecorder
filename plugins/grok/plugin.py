import logging
import os
from typing import TYPE_CHECKING

from ncatbot.core import registrar
from ncatbot.event.qq import GroupBanEvent, GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin

from .app import AgentRuntime, handle_event, handle_group_ban
from .config import AgentPluginSettings, build_config
from .infra import (
    AgentConversationSessionStore,
    AgentTraceStore,
    ProfileJsonStore,
    RecorderBridge,
)
from .trigger import CooldownTracker
from .vision.client import create_dashscope_client
from .vision.quota import VisionQuotaTracker

if TYPE_CHECKING:
    from openai import OpenAI


class GrokPlugin(NcatBotPlugin):
    name = "grok"
    version = "1.3.3"
    author = "Arsvine Zhu"
    description = "基于单 Agent 工具调用的独立回复插件"

    def __init__(self):
        super().__init__()
        self.settings: AgentPluginSettings = build_config({})
        self._bridge: RecorderBridge | None = None
        self._trace_store: AgentTraceStore | None = None
        self._cooldowns = CooldownTracker()
        self._vision_client: OpenAI | None = None
        self._vision_quota: VisionQuotaTracker | None = None
        self._profile_json_store: ProfileJsonStore | None = None
        self._conversation_store: AgentConversationSessionStore | None = None
        self._runtime: AgentRuntime | None = None

    async def on_load(self) -> None:
        self.settings = build_config(getattr(self, "config", {}) or {})
        if not self.settings.enabled:
            self.logger.info("grok loaded in disabled mode")
            return
        if not os.path.isabs(self.settings.recorder_db):
            raise ValueError("grok.recorder_db must be an absolute path")

        logging.getLogger("LiteLLM").setLevel(logging.WARNING)

        self._bridge = RecorderBridge()
        await self._bridge.connect_existing(self.settings.recorder_db)
        self._trace_store = AgentTraceStore(self.settings.recorder_db)
        await self._trace_store.init_db()
        self._conversation_store = AgentConversationSessionStore(
            self.settings.recorder_db
        )
        await self._conversation_store.init_db()
        profile_db_path = self.settings.profile.db_path
        if profile_db_path and not os.path.isabs(profile_db_path):
            profile_db_path = str(self.workspace / profile_db_path)
        self._profile_json_store = ProfileJsonStore(profile_db_path)
        await self._profile_json_store.init_db()
        await self._init_vision()
        self._runtime = AgentRuntime(self)
        self.logger.info("grok loaded | recorder_db=%s", self.settings.recorder_db)

    async def _init_vision(self) -> None:
        vision = self.settings.vision
        if not vision.enabled or not vision.dashscope_api_key:
            self.logger.info(
                "grok vision disabled (enabled=%s, key_set=%s)",
                vision.enabled,
                bool(vision.dashscope_api_key),
            )
            return
        try:
            self._vision_client = create_dashscope_client(vision.dashscope_api_key)
            self._vision_quota = VisionQuotaTracker(vision)
        except Exception as exc:
            self.logger.warning("grok vision init failed: %s", exc)
            self._vision_client = None
            self._vision_quota = None
            return
        self.logger.info("grok vision initialized")

    async def on_close(self) -> None:
        if self._bridge is not None:
            await self._bridge.close()
        if self._trace_store is not None:
            await self._trace_store.close()
        if self._conversation_store is not None:
            await self._conversation_store.close()
        if self._profile_json_store is not None:
            await self._profile_json_store.close()
        self._vision_client = None
        self._vision_quota = None
        self._profile_json_store = None
        self._conversation_store = None
        self._runtime = None
        self.logger.info("grok unloaded")

    @registrar.qq.on_group_message()
    async def on_group_message(self, event: GroupMessageEvent) -> None:
        await self._handle(event, "group")

    @registrar.qq.on_private_message()
    async def on_private_message(self, event: PrivateMessageEvent) -> None:
        await self._handle(event, "private")

    @registrar.qq.on_group_ban()
    async def on_group_ban(self, event: GroupBanEvent) -> None:
        await handle_group_ban(self, event)

    async def _handle(self, event, chat_type: str) -> None:
        await handle_event(self, event, chat_type)
