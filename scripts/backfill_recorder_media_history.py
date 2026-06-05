"""
Backfill recorder bot messages and media semantic text.

Usage:
    python scripts/backfill_recorder_media_history.py
    python scripts/backfill_recorder_media_history.py --dry-run --verbose
    python scripts/backfill_recorder_media_history.py --skip-bot-messages
    python scripts/backfill_recorder_media_history.py --skip-semantic-text
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path


def _load_backfill_module():
    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    from plugins.qq_recorder.backfill import (  # noqa: PLC0415
        backfill_bot_messages,
        backfill_semantic_texts,
        ensure_backfill_columns,
        resolve_bot_uin,
    )

    return (
        backfill_bot_messages,
        backfill_semantic_texts,
        ensure_backfill_columns,
        resolve_bot_uin,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill recorder bot messages and media semantic text"
    )
    parser.add_argument(
        "--db",
        default=str(
            Path(__file__).resolve().parent.parent
            / "data"
            / "qq_recorder"
            / "data"
            / "recorder.db"
        ),
        help="Recorder SQLite database path",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "config.yaml"),
        help="Root config.yaml path used to resolve bot_uin",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument(
        "--skip-bot-messages",
        action="store_true",
        help="Do not backfill historical bot messages from trace tables",
    )
    parser.add_argument(
        "--skip-semantic-text",
        action="store_true",
        help="Do not backfill semantic_text for media analyses",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print(f"Database not found: {args.db}")
        raise SystemExit(1)

    (
        backfill_bot_messages,
        backfill_semantic_texts,
        ensure_backfill_columns,
        resolve_bot_uin,
    ) = _load_backfill_module()

    bot_uin = resolve_bot_uin(args.config)
    if not args.skip_bot_messages and not bot_uin:
        print(f"bot_uin not found in config: {args.config}")
        raise SystemExit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        ensure_backfill_columns(conn)

        print(f"Database: {args.db}")
        print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

        if not args.skip_semantic_text:
            counts = backfill_semantic_texts(
                conn,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            print(
                "semantic_text:"
                f" scanned={counts.scanned}"
                f" updated={counts.updated}"
                f" skipped_unrecoverable={counts.skipped_unrecoverable}"
            )

        if not args.skip_bot_messages:
            counts = backfill_bot_messages(
                conn,
                bot_uin=bot_uin,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            print(
                "bot_messages:"
                f" scanned={counts.scanned}"
                f" inserted={counts.inserted}"
                f" skipped_existing={counts.skipped_existing}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
