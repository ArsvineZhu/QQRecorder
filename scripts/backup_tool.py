"""QQContextBot backup inspection and restore tool.

Usage:
    python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
    python scripts/backup_tool.py restore --archive path/to/backup.zip \
        --db-path data/qq_recorder/data/recorder.db \
        --images-dir data/qq_recorder/data/images
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import sqlite3
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def _extract_runtime_uris(config_path: Path) -> dict[str, str]:
    if not config_path.exists():
        return {}

    uri_pattern = re.compile(
        r"^\s*(ws_uri|webui_uri)\s*:\s*['\"]?([^'\"\s#]+)['\"]?\s*$"
    )
    uris: dict[str, str] = {}
    for line in config_path.read_text(encoding="utf-8").splitlines():
        match = uri_pattern.match(line)
        if match:
            uris[match.group(1)] = match.group(2)
    return uris


def _uri_is_reachable(uri: str, timeout: float = 0.3) -> bool:
    parsed = urlparse(uri)
    host = parsed.hostname
    if not host:
        return False

    port = parsed.port
    if port is None:
        if parsed.scheme in {"wss", "https"}:
            port = 443
        else:
            port = 80

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _db_is_busy(db_path: Path) -> tuple[bool, str]:
    if not db_path.exists():
        return False, ""

    try:
        connection = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    except sqlite3.Error:
        return False, ""

    try:
        connection.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        return True, str(exc)
    finally:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        connection.close()

    return False, ""


def _restore_blockers(db_path: Path, config_path: Path) -> list[str]:
    blockers: list[str] = []

    runtime_uris = _extract_runtime_uris(config_path)
    reachable = [
        f"{name}={uri}" for name, uri in runtime_uris.items() if _uri_is_reachable(uri)
    ]
    if reachable:
        blockers.append(
            "Detected active runtime endpoints: " + ", ".join(sorted(reachable))
        )

    busy, reason = _db_is_busy(db_path)
    if busy:
        blockers.append(f"Target SQLite database is busy/locked: {reason}")

    return blockers


def _load_manifest(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path, "r") as zip_file:
        with zip_file.open("manifest.json") as manifest_file:
            return json.loads(manifest_file.read().decode("utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQContextBot backup tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List backup archives")
    list_parser.add_argument(
        "--dir",
        dest="backup_dir",
        default="data/qq_recorder/data/backups",
        help="Directory that contains backup archives",
    )

    restore_parser = subparsers.add_parser("restore", help="Restore a backup chain")
    restore_parser.add_argument("--archive", required=True, help="Target backup zip")
    restore_parser.add_argument("--db-path", required=True, help="Target SQLite path")
    restore_parser.add_argument(
        "--images-dir", required=True, help="Target images directory"
    )
    restore_parser.add_argument(
        "--config",
        default=str(PROJECT_DIR / "config.yaml"),
        help=(
            "Project config path used for runtime status checks "
            "(default: ./config.yaml)"
        ),
    )
    restore_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass runtime status checks and force restore",
    )

    return parser


def _cmd_list(backup_dir: Path) -> int:
    if not backup_dir.exists():
        print(f"Backup directory not found: {backup_dir}", file=sys.stderr)
        return 1

    archives = sorted(backup_dir.glob("*.zip"))
    if not archives:
        print("No backup archives found")
        return 0

    for archive in archives:
        try:
            manifest = _load_manifest(archive)
            created_at = manifest.get("created_at", "")
            kind = manifest.get("kind", "")
            chain_id = manifest.get("chain_id", "")
            included_count = manifest.get("included_count", 0)
            print(
                f"{archive.name} | {kind} | {created_at} | "
                f"chain={chain_id} | files={included_count}"
            )
        except Exception as exc:
            print(f"{archive.name} | unreadable manifest: {exc}")
    return 0


def _cmd_restore(
    archive: Path, db_path: Path, images_dir: Path, config_path: Path, force: bool
) -> int:
    if not archive.exists():
        print(f"Backup archive not found: {archive}", file=sys.stderr)
        return 1

    if not force:
        blockers = _restore_blockers(db_path, config_path)
        if blockers:
            print(
                "Restore blocked: runtime precondition check failed.",
                file=sys.stderr,
            )
            for item in blockers:
                print(f"  - {item}", file=sys.stderr)
            print(
                (
                    "Stop the bot/runtime and retry. "
                    "Use --force only if you accept the risk."
                ),
                file=sys.stderr,
            )
            return 2

    from plugins.qq_recorder.backup import BackupConfig, BackupManager

    manager = BackupManager(
        BackupConfig(enabled=False, output_dir=str(archive.parent)),
        db_path=str(db_path),
        images_dir=str(images_dir),
    )
    restored_chain = asyncio.run(
        manager.restore_backup(str(archive), str(db_path), str(images_dir))
    )
    print("Restored archives:")
    for item in restored_chain:
        print(f"  {item}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "list":
        return _cmd_list(Path(args.backup_dir))
    if args.command == "restore":
        return _cmd_restore(
            Path(args.archive),
            Path(args.db_path),
            Path(args.images_dir),
            Path(args.config),
            bool(args.force),
        )

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
