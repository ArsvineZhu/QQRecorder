import asyncio
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from plugins.qq_recorder.backup import BackupConfig, BackupManager, BackupScheduler
from plugins.qq_recorder.config import build_config


def _create_snapshot_file(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO snapshots(body) VALUES ('initial')")
        connection.commit()
    finally:
        connection.close()


def _append_snapshot_row(db_path: Path, body: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("INSERT INTO snapshots(body) VALUES (?)", (body,))
        connection.commit()
    finally:
        connection.close()


def _read_manifest(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path, "r") as zip_file:
        with zip_file.open("manifest.json") as manifest_file:
            return json.loads(manifest_file.read().decode("utf-8"))


def _read_archived_row_count(archive_path: Path, db_name: str) -> int:
    extract_dir = archive_path.parent / "extract-check"
    if extract_dir.exists():
        for path in sorted(extract_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as zip_file:
        zip_file.extract(f"db/{db_name}", extract_dir)
    archived_db = extract_dir / "db" / db_name
    connection = sqlite3.connect(archived_db)
    try:
        row = connection.execute("SELECT COUNT(*) FROM messages").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_build_config_validates_backup_settings():
    config = build_config(
        {
            "backup": {
                "enabled": True,
                "output_dir": "data/backups",
                "keep_last": 3,
                "full_interval_days": 2,
                "full_time": "03:00",
                "incremental_times": ["12:00", "18:00"],
            }
        }
    )

    assert config.backup.enabled is True
    assert config.backup.keep_last == 3
    assert config.backup.full_interval_days == 2
    assert config.backup.incremental_times == ["12:00", "18:00"]

    with pytest.raises(ValueError):
        build_config({"backup": {"incremental_times": ["12:00", "12:00"]}})


def test_scheduler_prioritizes_full_over_incremental_when_overdue():
    scheduler = BackupScheduler(
        BackupConfig(
            enabled=True,
            output_dir="data/backups",
            keep_last=2,
            full_interval_days=2,
            full_time="03:00",
            incremental_times=["12:00"],
        )
    )

    now = datetime(2026, 5, 3, 13, 0)
    last_full_at = datetime(2026, 5, 1, 3, 0)
    last_backup_at = datetime(2026, 5, 2, 12, 0)

    assert scheduler.catch_up_action(now, last_backup_at, last_full_at) == "full"


def test_full_incremental_backup_and_restore_chain(tmp_path: Path):
    source_root = tmp_path / "source"
    db_path = source_root / "recorder.db"
    images_dir = source_root / "images"
    backups_dir = tmp_path / "backups"
    restore_db = tmp_path / "restore" / "recorder.db"
    restore_images = tmp_path / "restore" / "images"

    _create_snapshot_file(db_path)
    (images_dir / "2026" / "05" / "21").mkdir(parents=True, exist_ok=True)
    (images_dir / "2026" / "05" / "21" / "a.gif").write_bytes(b"gif-one")

    manager = BackupManager(
        BackupConfig(
            enabled=True,
            output_dir=str(backups_dir),
            keep_last=5,
            full_interval_days=2,
            full_time="03:00",
            incremental_times=["12:00"],
        ),
        db_path=str(db_path),
        images_dir=str(images_dir),
    )

    full_result = asyncio.run(
        manager.create_backup("full", now=datetime(2026, 5, 21, 3, 0))
    )
    assert full_result.ok is True
    assert full_result.kind == "full"
    assert full_result.included_files == 2

    (images_dir / "2026" / "05" / "21" / "b.png").write_bytes(b"png-two")
    incr_result = asyncio.run(
        manager.create_backup("incremental", now=datetime(2026, 5, 21, 12, 0))
    )
    assert incr_result.ok is True
    assert incr_result.kind == "incremental"
    assert incr_result.chain_id == full_result.chain_id
    assert incr_result.parent_archive == full_result.archive_name
    assert incr_result.included_files == 2

    assert full_result.archive_path is not None
    assert incr_result.archive_path is not None
    full_manifest = _read_manifest(Path(full_result.archive_path))
    incr_manifest = _read_manifest(Path(incr_result.archive_path))
    assert full_manifest["kind"] == "full"
    assert incr_manifest["kind"] == "incremental"
    assert incr_manifest["parent_archive"] == full_result.archive_name
    assert {entry["archive_path"] for entry in incr_manifest["included_files"]} == {
        f"db/{db_path.name}",
        "images/2026/05/21/b.png",
    }

    assert incr_result.archive_name is not None
    restored_chain = asyncio.run(
        manager.restore_backup(
            incr_result.archive_path,
            str(restore_db),
            str(restore_images),
        )
    )
    assert restored_chain[-1].endswith(incr_result.archive_name)
    assert restore_db.exists()
    assert (restore_images / "2026" / "05" / "21" / "a.gif").exists()
    assert (restore_images / "2026" / "05" / "21" / "b.png").exists()


def test_retention_keeps_chain_boundaries(tmp_path: Path):
    source_root = tmp_path / "source"
    db_path = source_root / "recorder.db"
    images_dir = source_root / "images"
    backups_dir = tmp_path / "backups"

    _create_snapshot_file(db_path)
    (images_dir / "2026" / "05" / "21").mkdir(parents=True, exist_ok=True)
    (images_dir / "2026" / "05" / "21" / "a.gif").write_bytes(b"gif-one")

    manager = BackupManager(
        BackupConfig(
            enabled=True,
            output_dir=str(backups_dir),
            keep_last=1,
            full_interval_days=2,
            full_time="03:00",
            incremental_times=["12:00"],
        ),
        db_path=str(db_path),
        images_dir=str(images_dir),
    )

    first_full = asyncio.run(
        manager.create_backup("full", now=datetime(2026, 5, 21, 3, 0))
    )
    asyncio.run(manager.create_backup("incremental", now=datetime(2026, 5, 21, 12, 0)))

    _append_snapshot_row(db_path, "second")

    (images_dir / "2026" / "05" / "23").mkdir(parents=True, exist_ok=True)
    (images_dir / "2026" / "05" / "23" / "c.png").write_bytes(b"png-three")

    second_full = asyncio.run(
        manager.create_backup("full", now=datetime(2026, 5, 23, 3, 0))
    )

    archives = sorted(backups_dir.glob("*.zip"))
    assert len(archives) == 1
    assert archives[0].name == second_full.archive_name
    assert second_full.chain_id != first_full.chain_id


def test_full_backup_includes_wal_commits(tmp_path: Path):
    source_root = tmp_path / "source"
    db_path = source_root / "recorder.db"
    images_dir = source_root / "images"
    backups_dir = tmp_path / "backups"

    images_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        assert journal_mode is not None
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO messages(body) VALUES ('first')")
        connection.commit()
        connection.execute("INSERT INTO messages(body) VALUES ('second')")
        connection.commit()
        manager = BackupManager(
            BackupConfig(
                enabled=True,
                output_dir=str(backups_dir),
                keep_last=3,
                full_interval_days=7,
                full_time="03:00",
                incremental_times=["12:00"],
            ),
            db_path=str(db_path),
            images_dir=str(images_dir),
        )

        result = asyncio.run(
            manager.create_backup("full", now=datetime(2026, 5, 21, 3, 0))
        )

        assert result.archive_path is not None
        assert _read_archived_row_count(Path(result.archive_path), db_path.name) == 2
    finally:
        connection.close()


def test_incremental_backup_includes_wal_commits(tmp_path: Path):
    source_root = tmp_path / "source"
    db_path = source_root / "recorder.db"
    images_dir = source_root / "images"
    backups_dir = tmp_path / "backups"
    restore_db = tmp_path / "restore" / "recorder.db"
    restore_images = tmp_path / "restore" / "images"

    images_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        assert journal_mode is not None
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO messages(body) VALUES ('first')")
        connection.commit()

        manager = BackupManager(
            BackupConfig(
                enabled=True,
                output_dir=str(backups_dir),
                keep_last=3,
                full_interval_days=7,
                full_time="03:00",
                incremental_times=["12:00"],
            ),
            db_path=str(db_path),
            images_dir=str(images_dir),
        )
        asyncio.run(manager.create_backup("full", now=datetime(2026, 5, 21, 3, 0)))

        connection.execute("INSERT INTO messages(body) VALUES ('second')")
        connection.commit()
        result = asyncio.run(
            manager.create_backup("incremental", now=datetime(2026, 5, 21, 12, 0))
        )

        assert result.archive_path is not None
        asyncio.run(
            manager.restore_backup(
                result.archive_path,
                str(restore_db),
                str(restore_images),
            )
        )
        restored_connection = sqlite3.connect(restore_db)
        try:
            row = restored_connection.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()
        finally:
            restored_connection.close()
        assert row is not None
        assert int(row[0]) == 2
    finally:
        connection.close()


def test_restore_failure_preserves_existing_targets(tmp_path: Path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    archive_path = backups_dir / "broken-full.zip"
    db_target = tmp_path / "restore" / "recorder.db"
    images_target = tmp_path / "restore" / "images"
    db_target.parent.mkdir(parents=True, exist_ok=True)
    db_target.write_text("keep-me", encoding="utf-8")
    (images_target / "2026" / "05" / "21").mkdir(parents=True, exist_ok=True)
    image_target = images_target / "2026" / "05" / "21" / "a.gif"
    image_target.write_bytes(b"keep-image")

    manifest = {
        "version": 1,
        "kind": "full",
        "created_at": "2026-05-21 03:00:00",
        "archive_name": archive_path.name,
        "chain_id": archive_path.name,
        "parent_archive": None,
        "database": str(db_target),
        "images_dir": str(images_target),
        "included_files": [],
        "snapshot_count": 0,
        "included_count": 0,
    }
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zip_file:
        zip_file.writestr("manifest.json", json.dumps(manifest))

    manager = BackupManager(
        BackupConfig(enabled=False, output_dir=str(backups_dir)),
        db_path=str(db_target),
        images_dir=str(images_target),
    )

    with pytest.raises(FileNotFoundError):
        asyncio.run(
            manager.restore_backup(
                str(archive_path),
                str(db_target),
                str(images_target),
            )
        )

    assert db_target.read_text(encoding="utf-8") == "keep-me"
    assert image_target.read_bytes() == b"keep-image"


def test_restore_rolls_back_db_when_image_swap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source_root = tmp_path / "source"
    db_path = source_root / "recorder.db"
    images_dir = source_root / "images"
    backups_dir = tmp_path / "backups"
    db_target = tmp_path / "restore" / "recorder.db"
    images_target = tmp_path / "restore" / "images"

    _create_snapshot_file(db_path)
    source_image = images_dir / "2026" / "05" / "21" / "new.gif"
    source_image.parent.mkdir(parents=True, exist_ok=True)
    source_image.write_bytes(b"new-image")

    manager = BackupManager(
        BackupConfig(enabled=True, output_dir=str(backups_dir)),
        db_path=str(db_path),
        images_dir=str(images_dir),
    )
    result = asyncio.run(manager.create_backup("full", now=datetime(2026, 5, 21, 3, 0)))
    assert result.archive_path is not None

    db_target.parent.mkdir(parents=True, exist_ok=True)
    db_target.write_text("keep-db", encoding="utf-8")
    existing_image = images_target / "2026" / "05" / "21" / "old.gif"
    existing_image.parent.mkdir(parents=True, exist_ok=True)
    existing_image.write_bytes(b"keep-image")

    real_move = shutil.move

    def fail_images_move(src: str, dst: str):
        if Path(dst) == images_target:
            raise OSError("images target is locked")
        return real_move(src, dst)

    monkeypatch.setattr("plugins.qq_recorder.backup.shutil.move", fail_images_move)

    with pytest.raises(OSError, match="images target is locked"):
        asyncio.run(
            manager.restore_backup(
                result.archive_path,
                str(db_target),
                str(images_target),
            )
        )

    assert db_target.read_text(encoding="utf-8") == "keep-db"
    assert existing_image.read_bytes() == b"keep-image"
    assert not (images_target / source_image.relative_to(images_dir)).exists()


def test_incremental_restore_removes_deleted_files(tmp_path: Path):
    source_root = tmp_path / "source"
    db_path = source_root / "recorder.db"
    images_dir = source_root / "images"
    backups_dir = tmp_path / "backups"
    restore_db = tmp_path / "restore" / "recorder.db"
    restore_images = tmp_path / "restore" / "images"

    _create_snapshot_file(db_path)
    original_image = images_dir / "2026" / "05" / "21" / "a.gif"
    original_image.parent.mkdir(parents=True, exist_ok=True)
    original_image.write_bytes(b"gif-one")

    manager = BackupManager(
        BackupConfig(
            enabled=True,
            output_dir=str(backups_dir),
            keep_last=5,
            full_interval_days=2,
            full_time="03:00",
            incremental_times=["12:00"],
        ),
        db_path=str(db_path),
        images_dir=str(images_dir),
    )

    full_result = asyncio.run(
        manager.create_backup("full", now=datetime(2026, 5, 21, 3, 0))
    )
    original_image.unlink()
    replacement_image = images_dir / "2026" / "05" / "21" / "b.png"
    replacement_image.write_bytes(b"png-two")

    incr_result = asyncio.run(
        manager.create_backup("incremental", now=datetime(2026, 5, 21, 12, 0))
    )

    asyncio.run(
        manager.restore_backup(
            str(incr_result.archive_path),
            str(restore_db),
            str(restore_images),
        )
    )

    assert full_result.archive_path is not None
    assert not (restore_images / "2026" / "05" / "21" / "a.gif").exists()
    assert (restore_images / "2026" / "05" / "21" / "b.png").exists()
