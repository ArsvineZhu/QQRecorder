"""
Migration script: deduplicate image records and add unique constraint.

Before v1.1.4, the images table had no unique constraint on (message_id, file_url).
This could cause:
  1. Duplicate image rows when the same message was processed multiple times
  2. SQLAlchemy MultipleResultsFound when multiple images in one message
     all had file_unique="0" (QQ's default)

This script:
  1. Detects existing constraint (skip if already applied)
  2. Deduplicates rows, keeping the first (lowest id) per (message_id, file_url)
  3. Rebuilds the images table with UniqueConstraint(message_id, file_url)

SQLite does not support ALTER TABLE ADD CONSTRAINT, so we use the
rename-and-swap pattern (create new → copy data → drop old → rename).

Usage:
    python scripts/fix_image_duplicates.py [--dry-run]
"""

import argparse
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def constraint_exists(conn: sqlite3.Connection) -> bool:
    """Check if a unique constraint on (message_id, file_url) exists on images table.

    After ALTER TABLE RENAME, SQLite renames named constraints to
    sqlite_autoindex_*, so we check by column coverage instead of name.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA index_list('images')")
    indexes = cur.fetchall()
    for idx in indexes:
        # idx[3] == 'u' means unique (in SQLite PRAGMA index_list format)
        if idx[3] != "u":
            continue
        idx_name = idx[1]
        cur2 = conn.cursor()
        cur2.execute(f"PRAGMA index_info('{idx_name}')")
        columns = [row[2] for row in cur2.fetchall()]
        if set(columns) == {"message_id", "file_url"}:
            return True
    return False


def count_duplicates(conn: sqlite3.Connection) -> int:
    """Count image rows that are duplicates on (message_id, file_url)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM images WHERE id NOT IN ("
        "  SELECT MIN(id) FROM images GROUP BY message_id, file_url"
        ")"
    )
    return cur.fetchone()[0]


def count_total(conn: sqlite3.Connection) -> int:
    """Count total rows in images table."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM images")
    return cur.fetchone()[0]


def list_duplicates(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """List duplicate groups for display. Returns up to `limit` groups."""
    cur = conn.cursor()
    cur.execute(
        "SELECT message_id, file_url, COUNT(*) as cnt "
        "FROM images "
        "GROUP BY message_id, file_url "
        "HAVING COUNT(*) > 1 "
        f"LIMIT {limit}"
    )
    rows = cur.fetchall()
    return [{"message_id": r[0], "file_url": r[1], "count": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

IMAGES_CREATE_SQL = (
    "CREATE TABLE images_new ("
    "  id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,"
    "  message_id INTEGER NOT NULL REFERENCES messages(id),"
    "  file_url VARCHAR,"
    "  file_unique VARCHAR,"
    "  file_size INTEGER,"
    "  local_path VARCHAR,"
    "  width INTEGER,"
    "  height INTEGER,"
    "  downloaded BOOLEAN DEFAULT 0,"
    "  CONSTRAINT _message_file_url_uc UNIQUE (message_id, file_url)"
    ")"
)


def migrate(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Apply the migration: deduplicate + add unique constraint."""
    dup_count = count_duplicates(conn)
    total = count_total(conn)

    if dup_count > 0:
        print(f"  Duplicate rows to remove: {dup_count} (of {total} total)")
        dup_groups = list_duplicates(conn)
        if dup_groups:
            print("  Sample duplicates:")
            for g in dup_groups[:10]:
                url_preview = (g["file_url"] or "")[:50]
                if len(url_preview) < len(g["file_url"] or ""):
                    url_preview += "..."
                print(
                    f"    message_id={g['message_id']}, "
                    f"file_url={url_preview}, x{g['count']}"
                )
            if len(dup_groups) > 10:
                print(f"    ... and {len(dup_groups) - 10} more groups")
    else:
        print(f"  No duplicate rows found (total: {total})")

    if dry_run:
        if dup_count > 0:
            print(f"  WOULD DELETE {dup_count} duplicate rows")
        print(
            "  WOULD CREATE images_new table with "
            "UniqueConstraint(message_id, file_url)"
        )
        print("  WOULD COPY deduplicated data to images_new")
        print("  WOULD DROP images, RENAME images_new TO images")
        return

    # Step 1: Delete duplicates (keep lowest id per group)
    if dup_count > 0:
        print("  Removing duplicate rows...")
        conn.execute(
            "DELETE FROM images WHERE id NOT IN ("
            "  SELECT MIN(id) FROM images GROUP BY message_id, file_url"
            ")"
        )
        print(f"  Deleted {dup_count} duplicate rows")

    # Step 2: Create new table with constraint
    print("  Creating images_new table with unique constraint...")
    conn.execute(IMAGES_CREATE_SQL)

    # Step 3: Copy data
    print("  Copying data to images_new...")
    conn.execute(
        "INSERT INTO images_new (id, message_id, file_url, file_unique, file_size, "
        "local_path, width, height, downloaded) "
        "SELECT id, message_id, file_url, file_unique, file_size, "
        "local_path, width, height, downloaded FROM images "
        "ORDER BY id"
    )

    # Step 4: Swap tables
    print("  Swapping tables...")
    conn.execute("DROP TABLE images")
    conn.execute("ALTER TABLE images_new RENAME TO images")

    conn.commit()
    print("  Migration complete!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate image records and add unique constraint"
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
    print(f"=== Fix Image Duplicates ({mode}) ===")
    print(f"Database: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    try:
        # Check if images table exists
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='images'"
        )
        if not cur.fetchone():
            print("  Table 'images' not found. Nothing to migrate.")
            return

        # Check if constraint already exists
        if constraint_exists(conn):
            print("  UniqueConstraint(message_id, file_url) already exists.")
            print("  No migration needed.")
            return

        print("  UniqueConstraint(message_id, file_url) is MISSING.")
        print()
        migrate(conn, args.dry_run)

        # Summary
        print()
        print("=== Summary ===")
        if not args.dry_run:
            print("  Added: UniqueConstraint(message_id, file_url) on images table")
            remaining = count_total(conn)
            print(f"  Remaining rows: {remaining}")
        else:
            print("  (dry run - no changes were applied)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
