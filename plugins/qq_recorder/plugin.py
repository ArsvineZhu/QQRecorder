import os

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin

from .commands import CommandHandler
from .config import build_config
from .events import event_to_dict
from .processors import MessageProcessor
from .storage import MessageStorage


class QQRecorderPlugin(NcatBotPlugin):
    name = "qq_recorder"
    version = "1.3.1"
    author = "Arsvine Zhu"
    description = "静默 QQ 消息记录器"

    def __init__(self):
        super().__init__()
        self.storage: MessageStorage
        self._command_handler: CommandHandler
        self._processor: MessageProcessor

    async def on_load(self):
        settings = build_config(self.config)

        db_path = settings.storage.database
        if not os.path.isabs(db_path):
            db_path = str(self.workspace / db_path)
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        images_dir = settings.storage.images_dir
        if not os.path.isabs(images_dir):
            images_dir = str(self.workspace / images_dir)
        os.makedirs(images_dir, exist_ok=True)
        settings.storage.images_dir = images_dir

        db_url = f"sqlite+aiosqlite:///{db_path}"
        self.storage = MessageStorage(db_url)
        await self.storage.init_db()

        self._command_handler = CommandHandler(self.storage, self.logger)
        self._processor = MessageProcessor(
            self.storage, settings, self.api, self.logger
        )

        self.logger.info(
            "QQRecorder loaded | monitor_all=%s | db=%s | images=%s",
            settings.monitor_all,
            db_path,
            images_dir,
        )

    async def on_close(self):
        if self.storage:
            await self.storage.close()
        self.logger.info("QQRecorder unloaded")

    @registrar.qq.on_group_command("recorder", "/recorder", "r", ignore_case=True)
    async def on_group_recorder(self, event: GroupMessageEvent):
        await self._command_handler.route(event)

    @registrar.qq.on_private_command("recorder", "/recorder", "r", ignore_case=True)
    async def on_private_recorder(self, event: PrivateMessageEvent):
        await self._command_handler.route(event)

    @registrar.qq.on_group_message()
    async def on_group_message(self, event: GroupMessageEvent):
        event_dict = event_to_dict(event)
        await self._processor.process_message(event_dict)

    @registrar.qq.on_private_message()
    async def on_private_message(self, event: PrivateMessageEvent):
        event_dict = event_to_dict(event)
        await self._processor.process_message(event_dict)
