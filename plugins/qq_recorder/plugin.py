import logging
import os
import re
from pathlib import Path

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin

from .backup import BackupManager
from .commands import CommandHandler
from .config import build_config
from .events import event_to_dict
from .outbound_recorder import install_outbound_recording
from .processors import MessageProcessor
from .storage import MessageStorage


class QQRecorderPlugin(NcatBotPlugin):
    name = "qq_recorder"
    version = "1.5.1"
    author = "Arsvine Zhu"
    description = "静默 QQ 消息记录器"

    def __init__(self):
        super().__init__()
        self.storage: MessageStorage
        self._command_handler: CommandHandler
        self._processor: MessageProcessor
        self._backup_manager: BackupManager | None = None

    async def on_load(self) -> None:
        _install_line_safe_logging()
        settings = build_config(self.config)

        db_path = settings.storage.database
        if not os.path.isabs(db_path):
            db_path = str(self.workspace / db_path)
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        settings.storage.database = db_path

        images_dir = settings.storage.images_dir
        if not os.path.isabs(images_dir):
            images_dir = str(self.workspace / images_dir)
        os.makedirs(images_dir, exist_ok=True)
        settings.storage.images_dir = images_dir

        videos_dir = settings.storage.videos_dir
        if not os.path.isabs(videos_dir):
            videos_dir = str(self.workspace / videos_dir)
        os.makedirs(videos_dir, exist_ok=True)
        settings.storage.videos_dir = videos_dir

        backup_dir = settings.backup.output_dir
        if not os.path.isabs(backup_dir):
            backup_dir = str(self.workspace / backup_dir)
        os.makedirs(backup_dir, exist_ok=True)
        settings.backup.output_dir = backup_dir

        self.storage = MessageStorage(
            settings.storage.database,
            lock_retry=settings.storage.lock_retry,
            logger=self.logger,
        )
        await self.storage.init_db()

        self._command_handler = CommandHandler(self.storage, self.logger)
        self._processor = MessageProcessor(
            self.storage, settings, self.api, self.logger
        )
        install_outbound_recording(
            self.api,
            self.storage,
            bot_uin=_resolve_bot_uin(),
            logger=self.logger,
        )
        self._backup_manager = BackupManager(
            settings.backup,
            settings.storage.database,
            settings.storage.images_dir,
            self.logger,
        )

        if settings.backup.enabled:
            try:
                await self._backup_manager.catch_up()
            except Exception as exc:
                self.logger.error("Backup catch-up failed: %s", exc, exc_info=True)

            self.add_scheduled_task(
                "qqrecorder_backup_full",
                settings.backup.full_time,
                callback=self._backup_manager.scheduled_full_backup,
            )
            for index, time_str in enumerate(settings.backup.incremental_times):
                self.add_scheduled_task(
                    f"qqrecorder_backup_incremental_{index}",
                    time_str,
                    callback=self._backup_manager.scheduled_incremental_backup,
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


def _resolve_bot_uin() -> str:
    config_path = Path("config.yaml")
    if not config_path.is_file():
        return ""
    text = config_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^bot_uin:\s*['\"]?(\d+)['\"]?\s*$", text, re.MULTILINE)
    return match.group(1) if match else ""


def _install_line_safe_logging() -> None:
    """Wrap root handlers' formatters to escape newlines in log output.

    Third-party loggers (NapCat adapter etc.) may emit messages containing
    literal newlines, breaking single-line log formats.  We wrap each root
    handler's formatter so the *final* formatted string is escaped — this is
    more reliable than a Filter because it runs after all %-expansion.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        fmt = getattr(handler, "formatter", None)
        if fmt is not None and not getattr(fmt, "_line_safe", False):
            handler.setFormatter(_LineSafeFormatter(fmt))


class _LineSafeFormatter(logging.Formatter):
    """Delegates formatting to *wrapped* then escapes newlines."""

    def __init__(self, wrapped: logging.Formatter):
        super().__init__()
        self._wrapped = wrapped
        self._line_safe = True  # marker to avoid double-wrapping

    def format(self, record: logging.LogRecord) -> str:
        text = self._wrapped.format(record)
        return text.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return self._wrapped.formatTime(record, datefmt)

    def formatException(self, ei) -> str:
        return self._wrapped.formatException(ei)

    def formatStack(self, stack_info: str) -> str:
        return self._wrapped.formatStack(stack_info)
