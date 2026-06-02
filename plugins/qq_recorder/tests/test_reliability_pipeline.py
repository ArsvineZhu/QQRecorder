import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from plugins.qq_recorder.config import build_config
from plugins.qq_recorder.processors import MessageProcessor
from plugins.qq_recorder.storage import MessageStorage


class _DummyAPI:
    class qq:
        class query:
            @staticmethod
            async def get_forward_msg(_forward_id: str) -> dict:
                return {"messages": []}


class _DummyLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None

    def error(self, *_args, **_kwargs) -> None:
        return None


def test_build_config_includes_reliability_defaults():
    config = build_config({})

    assert config.image.max_file_size == 52_428_800
    assert config.processing.max_inflight == 48
    assert config.processing.image_download_concurrency == 4
    assert config.storage.lock_retry.enabled is True
    assert config.storage.lock_retry.max_retries == 5
    assert config.storage.lock_retry.base_delay_ms == 50


def test_message_processor_respects_max_inflight_limit():
    class _StorageStub:
        AsyncSessionLocal = None

        def __init__(self) -> None:
            self.active = 0
            self.max_seen = 0
            self._lock = asyncio.Lock()

        async def save_message(self, _message_data: dict) -> int:
            async with self._lock:
                self.active += 1
                self.max_seen = max(self.max_seen, self.active)
            await asyncio.sleep(0.03)
            async with self._lock:
                self.active -= 1
            return 1

    async def _run() -> int:
        storage = _StorageStub()
        settings = build_config(
            {
                "monitor_all": True,
                "image": {"download": False},
                "forward": {"parse_content": False},
                "processing": {"max_inflight": 2},
                "backup": {"enabled": False},
            }
        )
        processor = MessageProcessor(
            storage=cast(Any, storage),
            settings=settings,
            api=_DummyAPI(),
            logger=_DummyLogger(),
        )

        async def _one(i: int) -> int | None:
            return await processor.process_message(
                {
                    "message_type": "group",
                    "message_id": f"m-{i}",
                    "user_id": "u1",
                    "group_id": "g1",
                    "time": 1_712_345_678,
                    "raw_message": f"hello {i}",
                    "message": [{"type": "text", "data": {"text": f"hello {i}"}}],
                    "sender": {"nickname": "tester", "card": ""},
                }
            )

        await asyncio.gather(*[_one(i) for i in range(10)])
        return storage.max_seen

    assert asyncio.run(_run()) <= 2


def test_storage_retries_lock_error_and_succeeds():
    async def _run() -> int:
        retry_cfg = build_config({}).storage.lock_retry
        storage = MessageStorage("dummy.db", lock_retry=retry_cfg)
        attempts = {"count": 0}

        async def _flaky() -> int:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OperationalError(
                    "INSERT ...",
                    {},
                    sqlite3.OperationalError("database is locked"),
                )
            return 7

        result = await storage._run_with_lock_retry("save_message", _flaky)
        assert attempts["count"] == 3
        return result

    assert asyncio.run(_run()) == 7


def test_image_fast_path_reuses_local_file_without_redownload(
    tmp_path: Path, monkeypatch
):
    async def _run() -> int:
        db_path = tmp_path / "recorder.db"
        images_dir = tmp_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        settings = build_config(
            {
                "monitor_all": True,
                "storage": {"database": str(db_path), "images_dir": str(images_dir)},
                "image": {
                    "download": True,
                    "timeout": 5,
                    "max_file_size": 52_428_800,
                },
                "forward": {"parse_content": False},
                "backup": {"enabled": False},
            }
        )

        storage = MessageStorage(str(db_path))
        await storage.init_db()
        processor = MessageProcessor(storage, settings, _DummyAPI(), _DummyLogger())

        download_calls = {"count": 0}

        async def _fake_download(*_args, **_kwargs):
            download_calls["count"] += 1
            return b"image-bytes", {"Content-Type": "image/png"}

        monkeypatch.setattr(
            "plugins.qq_recorder.image_handler.download_image", _fake_download
        )

        event_payload = {
            "message_type": "group",
            "user_id": "u1",
            "group_id": "g1",
            "time": int(datetime.now().timestamp()),
            "raw_message": "[CQ:image,file=abc.png,url=https://img.example/a.png]",
            "sender": {"nickname": "tester", "card": ""},
            "message": [
                {
                    "type": "image",
                    "data": {
                        "url": "https://img.example/a.png",
                        "file_unique": "0",
                        "file_size": 1024,
                    },
                }
            ],
        }

        first = dict(event_payload)
        first["message_id"] = "m-first"
        second = dict(event_payload)
        second["message_id"] = "m-second"

        first_id = await processor.process_message(first)
        second_id = await processor.process_message(second)

        assert first_id is not None
        assert second_id is not None

        first_msg = await storage.get_message("m-first")
        second_msg = await storage.get_message("m-second")
        assert first_msg is not None and first_msg.images
        assert second_msg is not None and second_msg.images
        assert first_msg.images[0].local_path
        assert second_msg.images[0].local_path == first_msg.images[0].local_path
        assert Path(first_msg.images[0].local_path).exists()

        await storage.close()
        return download_calls["count"]

    assert asyncio.run(_run()) == 1


def test_storage_init_db_adds_sender_columns_for_existing_database(tmp_path: Path):
    db_path = tmp_path / "recorder.db"
    engine = create_sync_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id VARCHAR NOT NULL UNIQUE,
                user_id VARCHAR NOT NULL,
                group_id VARCHAR,
                chat_type VARCHAR NOT NULL,
                timestamp DATETIME NOT NULL,
                raw_message TEXT NOT NULL,
                has_image BOOLEAN DEFAULT FALSE,
                has_reply BOOLEAN DEFAULT FALSE,
                has_forward BOOLEAN DEFAULT FALSE,
                has_at BOOLEAN DEFAULT FALSE,
                has_app_share BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    engine.dispose()

    async def _run() -> set[str]:
        storage = MessageStorage(str(db_path))
        await storage.init_db()
        await storage.close()
        inspector = inspect(create_sync_engine(f"sqlite:///{db_path}"))
        return {column["name"] for column in inspector.get_columns("messages")}

    columns = asyncio.run(_run())
    assert "sender_nickname" in columns
    assert "sender_card" in columns


def test_message_processor_persists_sender_display_fields(tmp_path: Path):
    async def _run():
        db_path = tmp_path / "recorder.db"
        settings = build_config(
            {
                "monitor_all": True,
                "image": {"download": False},
                "forward": {"parse_content": False},
                "backup": {"enabled": False},
                "storage": {"database": str(db_path)},
            }
        )
        storage = MessageStorage(str(db_path))
        await storage.init_db()
        processor = MessageProcessor(storage, settings, _DummyAPI(), _DummyLogger())

        message_id = await processor.process_message(
            {
                "message_type": "group",
                "message_id": "m-1",
                "user_id": "u1",
                "group_id": "g1",
                "time": 1_712_345_678,
                "raw_message": "hello",
                "message": [{"type": "text", "data": {"text": "hello"}}],
                "sender": {"nickname": "tester", "card": "群名片"},
            }
        )
        stored = await storage.get_message("m-1")
        await storage.close()
        return message_id, stored

    message_id, stored = asyncio.run(_run())
    assert message_id is not None
    assert stored is not None
    assert stored.sender_nickname == "tester"
    assert stored.sender_card == "群名片"
