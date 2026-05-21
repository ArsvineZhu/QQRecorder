from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from .config import BackupConfig

BackupKind = Literal["full", "incremental"]


@dataclass(slots=True)
class SnapshotEntry:
    source_type: str
    source_path: str
    archive_path: str
    size: int
    mtime_ns: int


@dataclass(slots=True)
class BackupState:
    last_backup_at: str | None = None
    last_full_at: str | None = None
    last_archive: str | None = None
    chain_id: str | None = None
    snapshot: dict[str, dict[str, int | str]] = field(default_factory=dict)
    version: int = 1

    @classmethod
    def load(cls, data: dict[str, Any] | None) -> BackupState:
        if not data:
            return cls()
        return cls(
            last_backup_at=data.get("last_backup_at"),
            last_full_at=data.get("last_full_at"),
            last_archive=data.get("last_archive"),
            chain_id=data.get("chain_id"),
            snapshot=data.get("snapshot", {}) or {},
            version=int(data.get("version", 1)),
        )

    def dump(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "last_backup_at": self.last_backup_at,
            "last_full_at": self.last_full_at,
            "last_archive": self.last_archive,
            "chain_id": self.chain_id,
            "snapshot": self.snapshot,
        }


@dataclass(slots=True)
class BackupResult:
    ok: bool
    kind: BackupKind
    archive_path: str | None = None
    archive_name: str | None = None
    chain_id: str | None = None
    parent_archive: str | None = None
    included_files: int = 0
    skipped: bool = False
    reason: str = ""


def _parse_hhmm(value: str) -> time:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"Invalid backup time: {value!r}") from exc
    return time(hour=parsed.hour, minute=parsed.minute)


def _dt_to_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat(sep=" ")


def _iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class BackupScheduler:
    def __init__(self, config: BackupConfig):
        self.config = config
        self.full_time = _parse_hhmm(config.full_time)
        self.incremental_times = [
            _parse_hhmm(value) for value in config.incremental_times
        ]

    def full_due_at(self, last_full_at: datetime | None) -> datetime | None:
        if last_full_at is None:
            return None
        next_date = last_full_at.date() + timedelta(days=self.config.full_interval_days)
        return datetime.combine(next_date, self.full_time)

    def is_full_due(self, now: datetime, last_full_at: datetime | None) -> bool:
        if last_full_at is None:
            return True
        due_at = self.full_due_at(last_full_at)
        return due_at is not None and now >= due_at

    def latest_missed_incremental(
        self, now: datetime, last_backup_at: datetime | None
    ) -> datetime | None:
        if last_backup_at is None:
            return None
        if not self.incremental_times:
            return None

        latest: datetime | None = None
        day_count = (now.date() - last_backup_at.date()).days
        for offset in range(day_count + 1):
            current_date = last_backup_at.date() + timedelta(days=offset)
            for value in self.incremental_times:
                candidate = datetime.combine(current_date, value)
                if last_backup_at < candidate <= now:
                    if latest is None or candidate > latest:
                        latest = candidate
        return latest

    def catch_up_action(
        self,
        now: datetime,
        last_backup_at: datetime | None,
        last_full_at: datetime | None,
    ) -> BackupKind | None:
        if last_full_at is None:
            return "full"
        if self.is_full_due(now, last_full_at):
            return "full"
        if self.latest_missed_incremental(now, last_backup_at) is not None:
            return "incremental"
        return None


class BackupManager:
    def __init__(
        self,
        config: BackupConfig,
        db_path: str,
        images_dir: str,
        logger: Any | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(db_path)
        self.images_dir = Path(images_dir)
        self.output_dir = Path(config.output_dir)
        self.state_path = self.output_dir / "backup_state.json"
        self.logger = logger
        self.scheduler = BackupScheduler(config)

    async def catch_up(self, now: datetime | None = None) -> BackupResult | None:
        now = now or datetime.now()
        state = self._load_state()
        last_backup_at = _iso_to_dt(state.last_backup_at)
        last_full_at = _iso_to_dt(state.last_full_at)
        action = self.scheduler.catch_up_action(now, last_backup_at, last_full_at)
        if action is None:
            return None
        return await self.create_backup(action, now=now)

    async def scheduled_full_backup(self, now: datetime | None = None) -> BackupResult:
        now = now or datetime.now()
        state = self._load_state()
        if not self.scheduler.is_full_due(now, _iso_to_dt(state.last_full_at)):
            return BackupResult(
                ok=True,
                kind="full",
                skipped=True,
                reason="full backup is not due yet",
            )
        return await self.create_backup("full", now=now)

    async def scheduled_incremental_backup(
        self, now: datetime | None = None
    ) -> BackupResult:
        now = now or datetime.now()
        return await self.create_backup("incremental", now=now)

    async def create_backup(
        self, kind: BackupKind, now: datetime | None = None
    ) -> BackupResult:
        now = now or datetime.now()
        return await asyncio.to_thread(self._create_backup_sync, kind, now)

    async def restore_backup(
        self,
        archive_path: str,
        db_target_path: str,
        images_target_dir: str,
    ) -> list[str]:
        return await asyncio.to_thread(
            self._restore_backup_sync, archive_path, db_target_path, images_target_dir
        )

    def list_archives(self) -> list[Path]:
        if not self.output_dir.exists():
            return []
        return sorted(self.output_dir.glob("*.zip"))

    def _load_state(self) -> BackupState:
        if not self.state_path.exists():
            return BackupState()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return BackupState()
        return BackupState.load(data)

    def _save_state(self, state: BackupState) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state.dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _collect_snapshot(self) -> dict[str, SnapshotEntry]:
        snapshot: dict[str, SnapshotEntry] = {}

        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        db_entry = self.db_path.stat()
        snapshot[f"db/{self.db_path.name}"] = SnapshotEntry(
            source_type="database",
            source_path=str(self.db_path),
            archive_path=f"db/{self.db_path.name}",
            size=db_entry.st_size,
            mtime_ns=db_entry.st_mtime_ns,
        )

        if self.images_dir.exists():
            for file_path in self.images_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                if self.output_dir in file_path.parents:
                    continue
                stat_result = file_path.stat()
                rel_path = file_path.relative_to(self.images_dir).as_posix()
                snapshot[f"images/{rel_path}"] = SnapshotEntry(
                    source_type="image",
                    source_path=str(file_path),
                    archive_path=f"images/{rel_path}",
                    size=stat_result.st_size,
                    mtime_ns=stat_result.st_mtime_ns,
                )

        return dict(sorted(snapshot.items(), key=lambda item: item[0]))

    @staticmethod
    def _snapshot_to_state(
        snapshot: dict[str, SnapshotEntry],
    ) -> dict[str, dict[str, int | str]]:
        return {
            key: {
                "source_type": value.source_type,
                "size": value.size,
                "mtime_ns": value.mtime_ns,
            }
            for key, value in snapshot.items()
        }

    @staticmethod
    def _state_to_snapshot(
        snapshot: dict[str, dict[str, int | str]],
    ) -> dict[str, dict[str, int | str]]:
        return snapshot or {}

    @staticmethod
    def _diff_snapshot(
        current: dict[str, SnapshotEntry],
        previous: dict[str, dict[str, int | str]],
    ) -> list[SnapshotEntry]:
        if not previous:
            return list(current.values())
        changed: list[SnapshotEntry] = []
        for key, entry in current.items():
            if entry.source_type == "database":
                changed.append(entry)
                continue
            prev = previous.get(key)
            if prev is None:
                changed.append(entry)
                continue
            if int(prev.get("size", -1)) != entry.size:
                changed.append(entry)
                continue
            if int(prev.get("mtime_ns", -1)) != entry.mtime_ns:
                changed.append(entry)
        return changed

    @staticmethod
    def _deleted_paths(
        current: dict[str, SnapshotEntry],
        previous: dict[str, dict[str, int | str]],
    ) -> list[str]:
        if not previous:
            return []
        current_keys = set(current)
        return sorted(key for key in previous if key not in current_keys)

    def _archive_name(self, kind: BackupKind, now: datetime) -> str:
        return f"qqrecorder-{now.strftime('%Y%m%d-%H%M%S')}-{kind}.zip"

    def _create_backup_sync(self, kind: BackupKind, now: datetime) -> BackupResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        state = self._load_state()
        current_snapshot = self._collect_snapshot()
        previous_snapshot = self._state_to_snapshot(state.snapshot)

        if kind == "incremental" and not previous_snapshot:
            kind = "full"

        if kind == "full":
            entries = list(current_snapshot.values())
            chain_id = self._archive_name(kind, now)
            parent_archive = None
            deleted_paths: list[str] = []
        else:
            entries = self._diff_snapshot(current_snapshot, previous_snapshot)
            deleted_paths = self._deleted_paths(current_snapshot, previous_snapshot)
            chain_id = state.chain_id or self._archive_name("full", now)
            parent_archive = state.last_archive

        archive_name = self._archive_name(kind, now)
        archive_path = self.output_dir / archive_name
        staging_dir = self.output_dir / ".staging" / archive_name.removesuffix(".zip")
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._populate_staging(staging_dir, entries)
            manifest = self._build_manifest(
                kind=kind,
                now=now,
                archive_name=archive_name,
                chain_id=chain_id,
                parent_archive=parent_archive,
                entries=entries,
                deleted_paths=deleted_paths,
                total_snapshot=current_snapshot,
            )
            manifest_path = staging_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._zip_staging(staging_dir, archive_path)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        state.last_backup_at = _dt_to_iso(now)
        state.last_archive = archive_name
        state.chain_id = chain_id
        state.snapshot = self._snapshot_to_state(current_snapshot)
        if kind == "full":
            state.last_full_at = _dt_to_iso(now)
        self._save_state(state)
        self._cleanup_old_chains()

        if self.logger:
            self.logger.info(
                "Backup created: kind=%s archive=%s included=%d",
                kind,
                archive_path,
                len(entries),
            )

        return BackupResult(
            ok=True,
            kind=kind,
            archive_path=str(archive_path),
            archive_name=archive_name,
            chain_id=chain_id,
            parent_archive=parent_archive,
            included_files=len(entries),
        )

    def _populate_staging(
        self, staging_dir: Path, entries: list[SnapshotEntry]
    ) -> None:
        for entry in entries:
            target = staging_dir / entry.archive_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.source_type == "database":
                self._copy_sqlite_snapshot(Path(entry.source_path), target)
            else:
                shutil.copy2(entry.source_path, target)

    @staticmethod
    def _copy_sqlite_snapshot(source_path: Path, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()
        source_conn = sqlite3.connect(source_path)
        dest_conn = sqlite3.connect(dest_path)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            source_conn.close()

    def _build_manifest(
        self,
        *,
        kind: BackupKind,
        now: datetime,
        archive_name: str,
        chain_id: str,
        parent_archive: str | None,
        entries: list[SnapshotEntry],
        deleted_paths: list[str],
        total_snapshot: dict[str, SnapshotEntry],
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "kind": kind,
            "created_at": _dt_to_iso(now),
            "archive_name": archive_name,
            "chain_id": chain_id,
            "parent_archive": parent_archive,
            "database": str(self.db_path),
            "images_dir": str(self.images_dir),
            "included_files": [
                {
                    "source_type": entry.source_type,
                    "archive_path": entry.archive_path,
                    "size": entry.size,
                    "mtime_ns": entry.mtime_ns,
                }
                for entry in entries
            ],
            "deleted_files": deleted_paths,
            "snapshot_count": len(total_snapshot),
            "included_count": len(entries),
        }

    @staticmethod
    def _zip_staging(staging_dir: Path, archive_path: Path) -> None:
        if archive_path.exists():
            archive_path.unlink()
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zip_file:
            for file_path in staging_dir.rglob("*"):
                if file_path.is_dir():
                    continue
                zip_file.write(file_path, file_path.relative_to(staging_dir).as_posix())

    def _restore_backup_sync(
        self, archive_path: str, db_target_path: str, images_target_dir: str
    ) -> list[str]:
        archive = Path(archive_path)
        if not archive.exists():
            raise FileNotFoundError(f"Backup archive not found: {archive}")

        chain = self._resolve_restore_chain(archive)
        target_manifest = self._read_manifest(chain[-1])
        db_name = Path(str(target_manifest.get("database", "recorder.db"))).name
        restore_root = Path(tempfile.mkdtemp(prefix="qqrecorder-restore-"))
        staging_root = Path(tempfile.mkdtemp(prefix="qqrecorder-restore-stage-"))
        try:
            for item in chain:
                with zipfile.ZipFile(item, "r") as zip_file:
                    zip_file.extractall(restore_root)
                manifest = self._read_manifest(item)
                self._apply_deleted_files(
                    restore_root,
                    [str(value) for value in manifest.get("deleted_files", [])],
                )

            db_target = Path(db_target_path)
            images_target = Path(images_target_dir)
            db_source = restore_root / "db" / db_name
            if not db_source.exists():
                raise FileNotFoundError(
                    f"Database payload missing from backup archive: {db_source}"
                )

            images_source = restore_root / "images"
            staged_db = staging_root / db_target.name
            shutil.copy2(db_source, staged_db)

            staged_images = staging_root / images_target.name
            if images_source.exists():
                shutil.copytree(images_source, staged_images)
            else:
                staged_images.mkdir(parents=True, exist_ok=True)

            db_target.parent.mkdir(parents=True, exist_ok=True)
            images_target.parent.mkdir(parents=True, exist_ok=True)
            self._replace_restore_targets(
                staged_db,
                db_target,
                staged_images,
                images_target,
            )
        finally:
            shutil.rmtree(restore_root, ignore_errors=True)
            shutil.rmtree(staging_root, ignore_errors=True)
        return [str(item) for item in chain]

    @staticmethod
    def _apply_deleted_files(restore_root: Path, deleted_files: list[str]) -> None:
        for relative_path in deleted_files:
            target = restore_root / relative_path
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target, ignore_errors=True)

    @classmethod
    def _replace_restore_targets(
        cls,
        staged_db: Path,
        db_target: Path,
        staged_images: Path,
        images_target: Path,
    ) -> None:
        db_backup = db_target.with_name(f".{db_target.name}.restore-bak")
        images_backup = images_target.with_name(f".{images_target.name}.restore-bak")
        cls._remove_path(db_backup)
        cls._remove_path(images_backup)

        db_existed = db_target.exists()
        images_existed = images_target.exists()
        db_backup_created = False
        images_backup_created = False
        try:
            if db_existed:
                db_target.replace(db_backup)
                db_backup_created = True
            if images_existed:
                images_target.replace(images_backup)
                images_backup_created = True

            shutil.move(str(staged_db), str(db_target))
            shutil.move(str(staged_images), str(images_target))
        except Exception:
            if (db_backup_created or not db_existed) and db_target.exists():
                cls._remove_path(db_target)
            if (images_backup_created or not images_existed) and images_target.exists():
                cls._remove_path(images_target)
            if db_backup_created and db_backup.exists():
                db_backup.replace(db_target)
            if images_backup_created and images_backup.exists():
                images_backup.replace(images_target)
            raise
        else:
            cls._remove_path(db_backup)
            cls._remove_path(images_backup)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()

    def _resolve_restore_chain(self, archive: Path) -> list[Path]:
        chain: list[Path] = []
        current = archive
        visited: set[Path] = set()
        while True:
            if current in visited:
                raise ValueError(f"Backup chain loop detected at {current}")
            visited.add(current)
            chain.append(current)
            manifest = self._read_manifest(current)
            parent_name = manifest.get("parent_archive")
            if not parent_name:
                break
            current = self.output_dir / str(parent_name)
            if not current.exists():
                raise FileNotFoundError(
                    f"Missing parent backup archive for restore: {current}"
                )
        chain.reverse()
        return chain

    @staticmethod
    def _read_manifest(archive: Path) -> dict[str, Any]:
        with zipfile.ZipFile(archive, "r") as zip_file:
            with zip_file.open("manifest.json") as manifest_file:
                return json.loads(manifest_file.read().decode("utf-8"))

    def _collect_chain_archives(self) -> list[tuple[datetime, str, list[Path]]]:
        archives = self.list_archives()
        chain_roots: list[tuple[datetime, str, list[Path]]] = []
        grouped: dict[str, list[Path]] = {}
        for archive in archives:
            try:
                manifest = self._read_manifest(archive)
            except Exception:
                continue
            chain_id = str(manifest.get("chain_id") or archive.name)
            grouped.setdefault(chain_id, []).append(archive)

        for chain_id, items in grouped.items():
            try:
                manifest = self._read_manifest(items[0])
            except Exception:
                continue
            created_at = _iso_to_dt(manifest.get("created_at"))
            if created_at is None:
                created_at = datetime.fromtimestamp(items[0].stat().st_mtime)
            chain_roots.append((created_at, chain_id, sorted(items)))

        chain_roots.sort(key=lambda item: item[0])
        return chain_roots

    def _cleanup_old_chains(self) -> None:
        chain_roots = self._collect_chain_archives()
        if len(chain_roots) <= self.config.keep_last:
            return

        for _, _, items in chain_roots[: -self.config.keep_last]:
            for archive in items:
                try:
                    archive.unlink()
                except FileNotFoundError:
                    pass

        if self.logger:
            self.logger.info(
                "Backup retention cleanup finished | keep_last=%d | chains=%d",
                self.config.keep_last,
                len(chain_roots),
            )
