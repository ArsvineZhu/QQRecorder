"""
QQContextBot database export & inspection tool.

Usage:
    python scripts/export_db.py summary  # Overview: row counts, date range
    python scripts/export_db.py schema   # Schema: columns, types, constraints
    python scripts/export_db.py table <name> [N]  # Dump rows from table (default: 20)
    python scripts/export_db.py messages [--chat TYPE] [--id ID] [-n N]
        # Messages with joined data
    python scripts/export_db.py images [--downloaded] [--missing] [-n N]
        # Image records
    python scripts/export_db.py search <keyword> [-n N]
        # Full-text search in raw_message
    python scripts/export_db.py export [--format FORMAT] [--output FILE]
        # Export entire DB as JSON/CSV
    python scripts/export_db.py stats    # Per-chat statistics
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime
from io import StringIO

# Fix Windows console encoding — GBK can't handle CJK/emoji in DB content
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# Text normalisation (handle both pre- and post-migration data)
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Normalize text for safe display/export by ensuring newlines are escaped.

    Handles both old (unescaped) and new (escaped) data in the DB:
    1. Unescape to recover original content
    2. Re-escape to produce consistent escaped output
    """
    if not text:
        return text
    # Unescape: convert stored \n → actual newline (handles new escaped data)
    # Then escape: convert actual newline → \n (handles old unescaped data)
    unescaped = text.replace("\\n", "\n").replace("\\t", "\t")
    return (
        unescaped.replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_DB = os.path.join(PROJECT_DIR, "data", "qq_recorder", "data", "recorder.db")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_ts(val) -> str:
    """Format a timestamp value for display."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val[:19] if len(val) > 19 else val
    return str(val)


def _fmt_size(size) -> str:
    """Format file size in human-readable form."""
    if size is None:
        return "?"
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024 / 1024:.1f}MB"


def _pct(part, total) -> str:
    """Format percentage."""
    if not total:
        return "0%"
    return f"{part / total * 100:.1f}%"


def _truncate(s, max_len=60):
    if not s:
        return ""
    return s[: max_len - 3] + "..." if len(s) > max_len else s


def _shorten_url(url: str, max_len=40) -> str:
    """Shorten a URL for display: keep domain + last query param."""
    if not url:
        return ""
    if len(url) <= max_len:
        return url
    # Split at '?': keep domain part + last query param
    if "?" in url:
        base, query = url.split("?", 1)
        params = query.split("&")
        last_param = params[-1] if params else ""
        shortened = f"{base}?...&{last_param}"
        if len(shortened) <= max_len:
            return shortened
        # Still too long: just domain + ...
        return _truncate(base + "?...", max_len)
    return _truncate(url, max_len)


def _shorten_path(path: str, max_len=40) -> str:
    """Shorten a file path for display: prefer relative path or just filename."""
    if not path:
        return ""
    # Try relative to project dir
    try:
        rel = os.path.relpath(path, PROJECT_DIR)
        if len(rel) < len(path):
            path = rel
    except ValueError:
        pass  # different drives on Windows
    if len(path) <= max_len:
        return path
    # Show filename only
    basename = os.path.basename(path)
    if len(basename) <= max_len:
        return f".../{basename}"
    return _truncate(basename, max_len)


def _fmt_cell(value, col_name: str, max_len=40) -> str:
    """Format a single cell for display based on column name heuristics."""
    if value is None:
        return "-"
    s = str(value)
    col_lower = col_name.lower()
    if col_lower.endswith("_url") or col_lower == "url":
        return _shorten_url(s, max_len)
    if col_lower.endswith("_path") or col_lower == "path" or col_lower == "local_path":
        return _shorten_path(s, max_len)
    return _truncate(s, max_len)


# Column name patterns that suggest free-form text — move these to the
# end and don't truncate
_TEXT_COL_PATTERNS = (
    "raw_message",
    "message",
    "content",
    "text",
    "description",
    "body",
    "summary",
)


def _is_text_col(col_name: str) -> bool:
    """Check if a column name suggests free-form text content."""
    lower = col_name.lower()
    return any(p in lower for p in _TEXT_COL_PATTERNS)


def _print_table(headers, rows, title=""):
    """Print a formatted ASCII table."""
    if title:
        print(f"\n  {title}")
        print(f"  {'-' * len(title)}")

    if not rows:
        print("  (no data)")
        return

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    sep = "  "
    header_line = sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(f"  {header_line}")
    print(f"  {'-' * len(header_line)}")

    for row in rows:
        line = sep.join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        print(f"  {line}")


def _get_table_names(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_summary(conn, _args):
    """Overview: table row counts, date range of messages."""
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    headers = ["Table", "Rows"]
    rows = []
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cur.fetchone()[0]
        rows.append([t, str(count)])
    _print_table(headers, rows, "Table Row Counts")

    # Message date range
    cur.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM messages")
    r = cur.fetchone()
    if r[0]:
        print(f"\n  Messages: {r[2]} total")
        print(f"  Date range: {_fmt_ts(r[0])} ~ {_fmt_ts(r[1])}")

    # Chat breakdown
    cur.execute(
        "SELECT chat_type, COUNT(*) FROM messages GROUP BY chat_type ORDER BY chat_type"
    )
    chat_rows = cur.fetchall()
    if chat_rows:
        print("\n  By chat type:")
        for cr in chat_rows:
            print(f"    {cr[0]}: {cr[1]} messages")

    # Image stats
    cur.execute(
        "SELECT COUNT(*), SUM(CASE WHEN downloaded THEN 1 ELSE 0 END) FROM images"
    )
    r = cur.fetchone()
    if r[0]:
        print(f"\n  Images: {r[0]} total, {r[1]} downloaded, {r[0] - r[1]} pending")

    # Distinct chats
    cur.execute(
        "SELECT chat_type, "
        "COUNT(DISTINCT CASE WHEN chat_type='group' THEN group_id ELSE user_id END) "
        "FROM messages GROUP BY chat_type"
    )
    chat_counts = cur.fetchall()
    if chat_counts:
        print("\n  Distinct chats:")
        for cc in chat_counts:
            label = "groups" if cc[0] == "group" else "private chats"
            print(f"    {cc[1]} {label}")

    print()


def cmd_schema(conn, _args):
    """Full table schema."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    for t in tables:
        cur.execute(f"PRAGMA table_info([{t}])")
        cols = cur.fetchall()
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        count = cur.fetchone()[0]

        headers = ["Column", "Type", "Nullable", "Default", "PK"]
        rows = []
        for c in cols:
            rows.append(
                [
                    c[1],
                    c[2],
                    "YES" if not c[3] else "NO",
                    str(c[4]) if c[4] is not None else "",
                    "PK" if c[5] else "",
                ]
            )
        _print_table(headers, rows, f"{t} ({count} rows)")

        # Foreign keys
        cur.execute(f"PRAGMA foreign_key_list([{t}])")
        fks = cur.fetchall()
        if fks:
            for fk in fks:
                print(f"    FK: {fk[3]} -> {fk[2]}.{fk[4]}")

        # Indexes
        cur.execute(f"PRAGMA index_list([{t}])")
        idxs = cur.fetchall()
        if idxs:
            print("    Indexes:")
            for idx in idxs:
                cur.execute(f"PRAGMA index_info([{idx[1]}])")
                idx_cols = [ic[2] for ic in cur.fetchall()]
                unique = "UNIQUE " if idx[2] else ""
                print(f"      {unique}{idx[1]}: {', '.join(idx_cols)}")

        print()


def cmd_table(conn, args):
    """Dump rows from a specific table, or list available tables."""
    table_name = args.table

    if not table_name:
        tables = _get_table_names(conn)
        print("Available tables:")
        for t in tables:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM [{t}]")
            count = cur.fetchone()[0]
            print(f"  {t} ({count} rows)")
        print()
        return

    limit = args.limit

    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    if not cur.fetchone():
        print(f"Error: table '{table_name}' not found")
        print(f"Available tables: {', '.join(_get_table_names(conn))}")
        return

    cur.execute(f"PRAGMA table_info([{table_name}])")
    col_info = cur.fetchall()
    col_names = [c[1] for c in col_info]

    cur.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    total = cur.fetchone()[0]

    cur.execute(f"SELECT * FROM [{table_name}] LIMIT ?", (limit,))
    rows = cur.fetchall()

    # Reorder: text-content columns go last, untruncated
    text_indices = [i for i, c in enumerate(col_names) if _is_text_col(c)]
    other_indices = [i for i in range(len(col_names)) if i not in text_indices]
    display_order = other_indices + text_indices

    ordered_names = [col_names[i] for i in display_order]
    display_rows = []
    for row in rows:
        display_row = []
        for idx in display_order:
            if idx in text_indices:
                display_row.append(
                    _normalize_text(str(row[idx])) if row[idx] is not None else "-"
                )
            else:
                display_row.append(_fmt_cell(row[idx], col_names[idx]))
        display_rows.append(display_row)

    _print_table(
        ordered_names, display_rows, f"{table_name} (showing {len(rows)}/{total} rows)"
    )
    print()


def cmd_messages(conn, args):
    """Messages with joined data."""
    cur = conn.cursor()

    conditions = []
    params = []

    if args.chat:
        conditions.append("chat_type = ?")
        params.append(args.chat)

    if args.id:
        conditions.append("(group_id = ? OR user_id = ?)")
        params.extend([args.id, args.id])

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    cur.execute(f"SELECT COUNT(*) FROM messages {where}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT id, message_id, user_id, group_id, chat_type, timestamp,
               raw_message, has_image, has_reply, has_forward, has_at
        FROM messages {where}
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        params + [args.limit],
    )
    rows = cur.fetchall()

    headers = ["ID", "MsgID", "User", "Group", "Type", "Time", "Flags", "Content"]
    display_rows = []
    for r in rows:
        flags = []
        if r[7]:
            flags.append("img")
        if r[8]:
            flags.append("reply")
        if r[9]:
            flags.append("fwd")
        if r[10]:
            flags.append("@")
        display_rows.append(
            [
                str(r[0]),
                r[1],
                r[2],
                r[3] or "-",
                r[4],
                _fmt_ts(r[5]),
                ",".join(flags) if flags else "-",
                _normalize_text(str(r[6])) if r[6] is not None else "-",
            ]
        )

    _print_table(headers, display_rows, f"Messages (showing {len(rows)}/{total})")
    print()


def cmd_images(conn, args):
    """Image records."""
    cur = conn.cursor()

    conditions = []
    params = []

    if args.downloaded:
        conditions.append("downloaded = 1")
    if args.missing:
        conditions.append("(downloaded = 0 OR local_path IS NULL)")

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    cur.execute(f"SELECT COUNT(*) FROM images {where}", params)
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT i.id, i.message_id, i.file_size, i.downloaded,
               i.local_path, i.width, i.height, m.chat_type, m.group_id, m.user_id
        FROM images i
        JOIN messages m ON i.message_id = m.id
        {where}
        ORDER BY i.id DESC
        LIMIT ?
        """,
        params + [args.limit],
    )
    rows = cur.fetchall()

    headers = ["ID", "MsgID", "Size", "DL", "Local Path", "WxH", "Chat"]
    display_rows = []
    for r in rows:
        size_str = _fmt_size(r[2])
        path_str = os.path.basename(r[4]) if r[4] else "(not downloaded)"
        dims = f"{r[5]}x{r[6]}" if r[5] and r[6] else "-"
        chat = r[7] or "?"
        chat_id = r[8] or r[9] or "?"
        display_rows.append(
            [
                str(r[0]),
                str(r[1]),
                size_str,
                "Y" if r[3] else "N",
                _truncate(path_str, 40),
                dims,
                f"{chat}:{chat_id}",
            ]
        )

    _print_table(headers, display_rows, f"Images (showing {len(rows)}/{total})")
    print()


def cmd_export(conn, args):  # noqa: C901
    """Export entire database as JSON or CSV."""
    fmt = args.format
    output = args.output

    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    data = {}
    for t in tables:
        cur.execute(f"SELECT * FROM [{t}]")
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]

        table_rows = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(col_names):
                val = row[i]
                # Normalize text fields to ensure consistent newline escaping
                if isinstance(val, str) and _is_text_col(col):
                    val = _normalize_text(val)
                elif (
                    isinstance(val, str)
                    and len(val) >= 10
                    and "20" in val[:4]
                    and "-" in val[4:5]
                ):
                    try:
                        dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S.%f")
                        val = dt.isoformat()
                    except ValueError:
                        try:
                            dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                            val = dt.isoformat()
                        except ValueError:
                            pass
                row_dict[col] = val
            table_rows.append(row_dict)
        data[t] = table_rows

    if fmt == "json":
        result = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    elif fmt == "csv":
        buf = StringIO()
        for t in tables:
            rows = data[t]
            if not rows:
                continue
            buf.write(f"# {t}\n")
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            buf.write("\n")
        result = buf.getvalue()
    else:
        print(f"Error: unsupported format '{fmt}'. Use 'json' or 'csv'.")
        return

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Exported to: {output} ({len(result)} bytes)")
    else:
        print(result)


def cmd_search(conn, args):
    """Full-text search in raw_message."""
    cur = conn.cursor()
    keyword = args.keyword
    limit = args.limit

    cur.execute(
        "SELECT COUNT(*) FROM messages WHERE raw_message LIKE ?",
        (f"%{keyword}%",),
    )
    total = cur.fetchone()[0]

    cur.execute(
        """
        SELECT id, message_id, user_id, group_id, chat_type, timestamp, raw_message,
               has_image, has_reply, has_forward, has_at
        FROM messages
        WHERE raw_message LIKE ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (f"%{keyword}%", limit),
    )
    rows = cur.fetchall()

    headers = ["ID", "User", "Group", "Time", "Content"]
    display_rows = []
    for r in rows:
        display_rows.append(
            [
                str(r[0]),
                r[2],
                r[3] or "-",
                _fmt_ts(r[5]),
                _normalize_text(str(r[6])) if r[6] is not None else "-",
            ]
        )

    _print_table(
        headers, display_rows, f'Search "{keyword}" ({len(rows)}/{total} results)'
    )
    print()


def cmd_stats(conn, _args):
    """Per-chat statistics."""
    cur = conn.cursor()

    # Group stats
    cur.execute(
        """
        SELECT group_id, COUNT(*) as cnt,
               SUM(has_image) as imgs,
               MIN(timestamp) as first_msg,
               MAX(timestamp) as last_msg
        FROM messages
        WHERE chat_type = 'group' AND group_id IS NOT NULL
        GROUP BY group_id
        ORDER BY cnt DESC
        """
    )
    groups = cur.fetchall()
    headers = ["Group ID", "Messages", "With Img", "First", "Last"]
    rows = [
        [r[0], str(r[1]), str(r[2] or 0), _fmt_ts(r[3]), _fmt_ts(r[4])] for r in groups
    ]
    _print_table(headers, rows, "Group Chat Statistics")

    # Private stats
    cur.execute(
        """
        SELECT user_id, COUNT(*) as cnt,
               SUM(has_image) as imgs,
               MIN(timestamp) as first_msg,
               MAX(timestamp) as last_msg
        FROM messages
        WHERE chat_type = 'private'
        GROUP BY user_id
        ORDER BY cnt DESC
        """
    )
    privates = cur.fetchall()
    headers = ["User ID", "Messages", "With Img", "First", "Last"]
    rows = [
        [r[0], str(r[1]), str(r[2] or 0), _fmt_ts(r[3]), _fmt_ts(r[4])]
        for r in privates
    ]
    _print_table(headers, rows, "Private Chat Statistics")

    # Top senders
    cur.execute(
        """
        SELECT user_id, COUNT(*) as cnt
        FROM messages
        GROUP BY user_id
        ORDER BY cnt DESC
        LIMIT 10
        """
    )
    top = cur.fetchall()
    headers = ["User ID", "Messages"]
    rows = [[r[0], str(r[1])] for r in top]
    _print_table(headers, rows, "Top 10 Senders")

    # Message type distribution
    cur.execute(
        """
        SELECT
            SUM(CASE WHEN has_image THEN 1 ELSE 0 END) as with_img,
            SUM(CASE WHEN has_reply THEN 1 ELSE 0 END) as with_reply,
            SUM(CASE WHEN has_forward THEN 1 ELSE 0 END) as with_fwd,
            SUM(CASE WHEN has_at THEN 1 ELSE 0 END) as with_at,
            COUNT(*) as total
        FROM messages
        """
    )
    r = cur.fetchone()
    if r:
        print("\n  Message composition:")
        print(f"    Total:      {r[4]}")
        print(f"    With image: {r[0]} ({_pct(r[0], r[4])})")
        print(f"    With reply: {r[1]} ({_pct(r[1], r[4])})")
        print(f"    With fwd:   {r[2]} ({_pct(r[2], r[4])})")
        print(f"    With @:     {r[3]} ({_pct(r[3], r[4])})")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

COMMANDS = {
    "summary": cmd_summary,
    "schema": cmd_schema,
    "table": cmd_table,
    "messages": cmd_messages,
    "images": cmd_images,
    "search": cmd_search,
    "stats": cmd_stats,
    "export": cmd_export,
}


def cmd_help(_conn, _args):
    """Show help (alias for --help)."""


COMMANDS["help"] = cmd_help


def main():
    parser = argparse.ArgumentParser(
        description="QQContextBot database export & inspection tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB, help=f"Database path (default: {DEFAULT_DB})"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # summary
    sub = subparsers.add_parser(
        "summary", help="Overview: table row counts, date range"
    )

    # schema
    sub = subparsers.add_parser("schema", help="Full table schema")

    # help
    sub = subparsers.add_parser("help", help="Show this help message")

    # table
    sub = subparsers.add_parser(
        "table", help="Dump rows from a table (no args = list tables)"
    )
    sub.add_argument(
        "table",
        nargs="?",
        default=None,
        help="Table name (omit to list available tables)",
    )
    sub.add_argument(
        "limit", nargs="?", type=int, default=20, help="Row limit (default: 20)"
    )

    # messages
    sub = subparsers.add_parser("messages", help="Messages with joined data")
    sub.add_argument("--chat", choices=["group", "private"], help="Filter by chat type")
    sub.add_argument("--id", help="Filter by group_id or user_id")
    sub.add_argument(
        "-n", "--limit", type=int, default=20, help="Row limit (default: 20)"
    )

    # images
    sub = subparsers.add_parser("images", help="Image records")
    sub.add_argument("--downloaded", action="store_true", help="Only downloaded images")
    sub.add_argument(
        "--missing", action="store_true", help="Only missing/undownloaded images"
    )
    sub.add_argument(
        "-n", "--limit", type=int, default=20, help="Row limit (default: 20)"
    )

    # search
    sub = subparsers.add_parser("search", help="Full-text search in raw_message")
    sub.add_argument("keyword", help="Search keyword")
    sub.add_argument(
        "-n", "--limit", type=int, default=20, help="Result limit (default: 20)"
    )

    # stats
    sub = subparsers.add_parser("stats", help="Per-chat statistics")

    # export
    sub = subparsers.add_parser("export", help="Export entire DB as JSON/CSV")
    sub.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Export format (default: json)",
    )
    sub.add_argument("--output", "-o", help="Output file path (default: stdout)")

    args = parser.parse_args()

    if not args.command or args.command == "help":
        parser.print_help()
        sys.exit(0)

    if not os.path.isfile(args.db):
        print(f"Error: database not found: {args.db}")
        sys.exit(1)

    conn = _connect(args.db)
    try:
        COMMANDS[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
