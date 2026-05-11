"""Add has_app_share column to messages and create app_shares table.

Usage:
    python scripts/migrate_add_app_share.py --dry-run
    python scripts/migrate_add_app_share.py
"""

import argparse
import os
import sys

from sqlalchemy import create_engine, inspect, text


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in columns


def main():
    parser = argparse.ArgumentParser(
        description="Add has_app_share column to messages and create app_shares table"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview only, do not modify"
    )
    parser.add_argument(
        "--db",
        default="data/qq_recorder/data/recorder.db",
        help=(
            "Path to the recorder.db file (default: data/qq_recorder/data/recorder.db)"
        ),
    )
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Migration: Add has_app_share + app_shares table ({mode}) ===")
    print(f"Database: {db_path}\n")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    # Check messages table
    table_names = inspector.get_table_names()
    if "messages" not in table_names:
        print("ERROR: 'messages' table not found.")
        sys.exit(1)

    with engine.connect() as conn:
        # 1. Add has_app_share column to messages
        has_has_app_share = column_exists(inspector, "messages", "has_app_share")
        if has_has_app_share:
            print("  has_app_share column already exists in messages.")
        else:
            print("  Adding column 'has_app_share' to messages...")
            if not args.dry_run:
                conn.execute(
                    text(
                        "ALTER TABLE messages "
                        "ADD COLUMN has_app_share BOOLEAN DEFAULT FALSE"
                    )
                )
                conn.commit()
            print("    [OK] has_app_share column added.")

        # 2. Create app_shares table if not exists
        has_app_shares = "app_shares" in table_names
        if has_app_shares:
            print("  app_shares table already exists.")
        else:
            print("  Creating app_shares table...")
            if not args.dry_run:
                conn.execute(
                    text(
                        """
                        CREATE TABLE app_shares (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            message_id INTEGER NOT NULL,
                            app_name VARCHAR DEFAULT '',
                            title VARCHAR DEFAULT '',
                            description VARCHAR DEFAULT '',
                            url VARCHAR DEFAULT '',
                            prompt VARCHAR DEFAULT '',
                            raw_data TEXT DEFAULT '',
                            FOREIGN KEY (message_id) REFERENCES messages (id)
                        )
                        """
                    )
                )
                conn.commit()
            print("    [OK] app_shares table created.")

    if not has_has_app_share or not has_app_shares:
        print("\nMigration complete.")
    else:
        print("\nNothing to migrate — schema already up to date.")


if __name__ == "__main__":
    main()
