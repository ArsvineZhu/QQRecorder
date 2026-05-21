"""QQRecorder backup inspection and restore tool.

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
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def _load_manifest(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path, "r") as zip_file:
        with zip_file.open("manifest.json") as manifest_file:
            return json.loads(manifest_file.read().decode("utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQRecorder backup tool")
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


def _cmd_restore(archive: Path, db_path: Path, images_dir: Path) -> int:
    if not archive.exists():
        print(f"Backup archive not found: {archive}", file=sys.stderr)
        return 1

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
            Path(args.archive), Path(args.db_path), Path(args.images_dir)
        )

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
