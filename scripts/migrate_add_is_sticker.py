"""
Migration script: add is_sticker and sticker_confidence fields to images table.

This migration adds two fields to support sticker detection:
- is_sticker: BOOLEAN DEFAULT FALSE - whether the image is identified as a sticker
- sticker_confidence: FLOAT DEFAULT 0.0 - confidence score of the sticker detection

Usage:
    python scripts/migrate_add_is_sticker.py [--dry-run]
"""

import argparse
import os
import sys
from sqlalchemy import create_engine, inspect, text

def column_exists(inspector, table_name: str, column_name: str) -> bool:
    """Check if a column already exists in the table."""
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns

def main():
    parser = argparse.ArgumentParser(
        description="Add is_sticker and sticker_confidence fields to images table"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying them"
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    db_path = os.path.join(project_dir, "data", "qq_recorder", "data", "recorder.db")

    if not os.path.isfile(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Migration: Add is_sticker and sticker_confidence to images table ({mode}) ===")
    print(f"Database: {db_path}")
    print()

    # Create SQLAlchemy engine (sync for migration)
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    # Check if images table exists
    if not inspector.has_table("images"):
        print("  Table 'images' not found. Nothing to migrate.")
        sys.exit(1)

    # Check existing columns
    has_is_sticker = column_exists(inspector, "images", "is_sticker")
    has_sticker_confidence = column_exists(inspector, "images", "sticker_confidence")

    if has_is_sticker and has_sticker_confidence:
        print("  Both columns already exist.")
        print("  No migration needed.")
        return

    # Report status
    missing = []
    if not has_is_sticker:
        missing.append("is_sticker (BOOLEAN DEFAULT FALSE)")
    if not has_sticker_confidence:
        missing.append("sticker_confidence (FLOAT DEFAULT 0.0)")

    print(f"  Missing columns: {len(missing)}")
    for col in missing:
        print(f"    - {col}")
    print()

    if args.dry_run:
        print(f"  WOULD add {len(missing)} column(s) to the images table.")
        print("  (dry run - no changes were applied)")
        return

    # Execute migration
    with engine.connect() as conn:
        if not has_is_sticker:
            print("  Adding column 'is_sticker'...")
            conn.execute(text("ALTER TABLE images ADD COLUMN is_sticker BOOLEAN DEFAULT FALSE"))
        
        if not has_sticker_confidence:
            print("  Adding column 'sticker_confidence'...")
            conn.execute(text("ALTER TABLE images ADD COLUMN sticker_confidence FLOAT DEFAULT 0.0"))
        
        conn.commit()

    print()
    print("=== Summary ===")
    added = 0
    if not has_is_sticker:
        added += 1
    if not has_sticker_confidence:
        added += 1
    print(f"  Added columns: {added}")
    print("  Migration complete!")

if __name__ == "__main__":
    main()
