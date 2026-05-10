"""
Migration script: escape newline/carriage-return/tab characters in stored text fields.

Before v1.1.3, message content was stored with literal control characters,
which could break single-line display and export formatting. This script
scans the database and escapes them to their string representations.

Affected columns:
  - messages.raw_message
  - forward_messages.content_summary

Transformations:
    \\r\\n  →  \\n    (CRLF → LF escape)
    \\r     →  \\n    (lone CR → LF escape)
    \\n     →  \\n    (LF escape)
    \\t     →  \\t    (TAB escape)

Usage:
    python scripts/fix_newline_escaping.py [--dry-run]
"""

import argparse
import os
import sqlite3
import sys

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Escape logic (same as text_utils.escape_text)
# ---------------------------------------------------------------------------


def escape_text(text: str) -> str:
    """Escape control characters in text for safe single-line storage."""
    if not text:
        return text
    return (
        text.replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def needs_escaping(text: str) -> bool:
    """Check if text contains any unescaped control characters."""
    if not text:
        return False
    return "\n" in text or "\r" in text or "\t" in text


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

TEXT_COLUMNS = [
    ("messages", "raw_message"),
    ("forward_messages", "content_summary"),
]


def scan_table(
    conn: sqlite3.Connection, table: str, column: str
) -> list[tuple[int, str, str]]:
    """Find rows where the column contains unescaped control characters.

    Returns list of (row_id, current_value, escaped_value).
    """
    cur = conn.cursor()
    cur.execute(f"SELECT id, {column} FROM [{table}] WHERE {column} IS NOT NULL")
    rows = cur.fetchall()

    results = []
    for row_id, value in rows:
        if not isinstance(value, str) or not needs_escaping(value):
            continue
        escaped = escape_text(value)
        if escaped != value:
            results.append((row_id, value, escaped))
    return results


def fix_table(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    fixes: list[tuple[int, str, str]],
    dry_run: bool,
) -> int:
    """Apply escaping fixes to the table. Returns number of updated rows."""
    if not fixes:
        return 0

    cur = conn.cursor()
    updated = 0
    for row_id, old_val, new_val in fixes:
        if not dry_run:
            cur.execute(
                f"UPDATE [{table}] SET [{column}] = ? WHERE id = ?",
                (new_val, row_id),
            )
        updated += 1
        action = "WOULD FIX" if dry_run else "FIXED"

        # Show a short preview of the change
        old_preview = (
            old_val.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        )
        if len(old_preview) > 60:
            old_preview = old_preview[:57] + "..."
        new_preview = new_val
        if len(new_preview) > 60:
            new_preview = new_preview[:57] + "..."
        print(f"  {action} {table}.id={row_id}:")
        print(f"    before: {old_preview}")
        print(f"    after:  {new_preview}")

    if not dry_run:
        conn.commit()
    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Escape newline/carriage-return/tab characters in stored text fields"
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
    print(f"=== Fix Newline Escaping ({mode}) ===")
    print(f"Database: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    try:
        total_fixed = 0
        for table, column in TEXT_COLUMNS:
            # Check table exists
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not cur.fetchone():
                print(f"  Table '{table}' not found, skipping.")
                continue

            print(f"Scanning {table}.{column}...")
            fixes = scan_table(conn, table, column)
            print(f"  Found {len(fixes)} rows needing fix")

            if fixes:
                print(f"  Fixing {table}.{column}...")
                count = fix_table(conn, table, column, fixes, args.dry_run)
                total_fixed += count
            print()

        # Summary
        print("=== Summary ===")
        print(f"  Total rows fixed: {total_fixed}")
        if args.dry_run:
            print("  (dry run - no changes were applied)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
