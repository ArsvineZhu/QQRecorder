"""
Backfill script: detect sticker flags for existing image records.

Scans images where sticker_confidence == 0.0 and runs the sticker
detection pipeline to populate is_sticker and sticker_confidence fields.

Usage:
    python scripts/backfill_sticker_flags.py [--dry-run] [--start-id N] [--end-id N] [--verbose]
"""

import argparse
import json
import os
import sqlite3
import sys


# ---------------------------------------------------------------------------
# Detection — uses the real sticker_detector module
# ---------------------------------------------------------------------------


def _import_detector():
    """Lazy import to avoid loading plugin deps at script top level."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    import importlib
    mod = importlib.import_module("plugins.qq_recorder.sticker_detector")
    return mod.combined_detection


def process_record(
    image_id: int,
    raw_message: str,
    segment_data: str | None,
    file_ext: str | None,
    file_size: int | None,
) -> tuple[bool, float]:
    """Run sticker detection on a single image record using real detection logic."""
    combined_detection = _import_detector()

    seg_dict = None
    if segment_data:
        try:
            seg_dict = json.loads(segment_data)
        except (json.JSONDecodeError, TypeError):
            seg_dict = None

    is_sticker, confidence = combined_detection(
        raw_message=raw_message,
        segment_data=seg_dict,
        file_size=file_size,
        file_ext=file_ext,
    )
    return is_sticker, confidence


# ---------------------------------------------------------------------------
# Record counts
# ---------------------------------------------------------------------------


def count_pending(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM images WHERE sticker_confidence == 0.0")
    return cur.fetchone()[0]


def count_total(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM images")
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def fetch_image_records(
    conn: sqlite3.Connection, start_id: int | None, end_id: int | None
) -> list[dict]:
    """Fetch image records that need backfilling, optionally filtered by id range.

    Uses two-phase fetch: get image records first, then batch-query
    associated message text and segment data. This avoids row duplication
    from the LEFT JOIN with message_segments (one message can have many
    segments, and one message can have many images).
    """
    conditions = ["i.sticker_confidence == 0.0"]
    params: list = []

    if start_id is not None:
        conditions.append("i.id >= ?")
        params.append(start_id)
    if end_id is not None:
        conditions.append("i.id <= ?")
        params.append(end_id)

    where = " AND ".join(conditions)

    cur = conn.cursor()
    cur.execute(
        f"SELECT i.id, i.file_url, i.file_size, i.local_path, i.message_id "
        f"FROM images i WHERE {where} ORDER BY i.id",
        params,
    )
    rows = cur.fetchall()

    if not rows:
        return []

    results = []
    message_ids = set()
    for row in rows:
        results.append(
            {
                "id": row[0],
                "file_url": row[1],
                "file_size": row[2],
                "local_path": row[3],
                "message_id": row[4],
                "raw_message": "",
                "segment_data": None,
            }
        )
        message_ids.add(row[4])

    # Phase 2: batch-query messages for raw_message
    mid_list = sorted(message_ids)
    placeholders = ",".join("?" for _ in mid_list)
    msg_map: dict[int, str] = {}
    cur.execute(
        f"SELECT id, raw_message FROM messages WHERE id IN ({placeholders})",
        mid_list,
    )
    for mid, raw_msg in cur.fetchall():
        msg_map[mid] = raw_msg or ""

    # Phase 3: batch-query image-type segment_data (one per message)
    seg_map: dict[int, str | None] = {}
    cur.execute(
        f"SELECT message_id, segment_data "
        f"FROM message_segments "
        f"WHERE segment_type = 'image' AND message_id IN ({placeholders}) "
        f"GROUP BY message_id",
        mid_list,
    )
    for mid, seg_data in cur.fetchall():
        seg_map[mid] = seg_data

    for rec in results:
        rec["raw_message"] = msg_map.get(rec["message_id"], "")
        rec["segment_data"] = seg_map.get(rec["message_id"])

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Backfill is_sticker / sticker_confidence for existing images"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without applying changes"
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=None,
        help="Start processing from this image id (inclusive)",
    )
    parser.add_argument(
        "--end-id",
        type=int,
        default=None,
        help="Stop processing at this image id (inclusive)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print detailed per-record info"
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    db_path = os.path.join(project_dir, "data", "qq_recorder", "data", "recorder.db")

    if not os.path.isfile(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Backfill Sticker Flags ({mode}) ===")
    print(f"Database: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images'")
        if not cur.fetchone():
            print("  Table 'images' not found. Nothing to backfill.")
            return

        cur.execute(
            "SELECT name FROM pragma_table_info('images') WHERE name IN ('is_sticker', 'sticker_confidence')"
        )
        existing = {r[0] for r in cur.fetchall()}
        if "is_sticker" not in existing or "sticker_confidence" not in existing:
            print("  Target columns missing. Run migrate_add_is_sticker.py first.")
            return

        pending = count_pending(conn)
        total = count_total(conn)

        if pending == 0:
            print(f"  No pending records. All {total} images already processed.")
            return

        print(f"  Pending records: {pending} / {total}")
        print()

        if args.start_id is not None or args.end_id is not None:
            range_desc = []
            if args.start_id is not None:
                range_desc.append(f"start_id={args.start_id}")
            if args.end_id is not None:
                range_desc.append(f"end_id={args.end_id}")
            print(f"  Filter: {' '.join(range_desc)}")

        records = fetch_image_records(conn, args.start_id, args.end_id)
        print(f"  Records to process: {len(records)}")
        print()

        if not records:
            print("Nothing to process.")
            return

        stickers_detected = 0
        processed = 0
        batch_size = 100

        for i, rec in enumerate(records, 1):
            ext = None
            if rec["local_path"]:
                _, ext = os.path.splitext(rec["local_path"])

            is_sticker, confidence = process_record(
                image_id=rec["id"],
                raw_message=rec["raw_message"],
                segment_data=rec["segment_data"],
                file_ext=ext,
                file_size=rec["file_size"],
            )

            if is_sticker:
                stickers_detected += 1

            if args.verbose:
                url_preview = (rec["file_url"] or "")[:60]
                status = "STICKER" if is_sticker else "image"
                print(
                    f"    [{i}/{len(records)}] id={rec['id']} "
                    f"conf={confidence:.2f} {status} {url_preview}"
                )

            if not args.dry_run:
                cur.execute(
                    "UPDATE images SET is_sticker = ?, sticker_confidence = ? WHERE id = ?",
                    (is_sticker, confidence, rec["id"]),
                )
            processed += 1

            if not args.dry_run and processed % batch_size == 0:
                conn.commit()
                print(f"  Committed batch at record {processed}...")

        if not args.dry_run and processed > 0:
            conn.commit()

        print()
        print("=== Summary ===")
        print(f"  Total processed: {processed}")
        print(f"  Stickers detected: {stickers_detected}")
        if args.dry_run:
            print("  (dry run - no changes were applied)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
