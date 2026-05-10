"""
Migration script: fix image file extensions based on magic bytes.

Scans stored images, detects actual format from binary content,
renames mismatched files, and updates the database.

Usage:
    python scripts/fix_image_extensions.py [--dry-run]
"""

import argparse
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Magic byte signatures (same logic as image_handler.py)
# ---------------------------------------------------------------------------

MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"GIF8", "gif"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"RIFF", "webp"),
    (b"BM", "bmp"),
]

EXT_MAP = {
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".gif": "gif",
    ".webp": "webp",
    ".bmp": "bmp",
}


def detect_format(data: bytes) -> str:
    """Detect image format from magic bytes. Returns extension without dot."""
    if not data or len(data) < 4:
        return ""
    for signature, ext in MAGIC_SIGNATURES:
        if data[: len(signature)] == signature:
            if ext == "webp" and len(data) >= 12:
                if data[8:12] != b"WEBP":
                    continue
            return ext
    return ""


def scan_images(images_dir: str) -> list[dict]:
    """Scan all image files and detect their actual format."""
    results = []
    for root, _dirs, files in os.walk(images_dir):
        for fname in files:
            filepath = os.path.join(root, fname)
            _, current_ext = os.path.splitext(fname)
            current_ext_lower = current_ext.lower()

            if current_ext_lower not in EXT_MAP:
                continue

            with open(filepath, "rb") as f:
                header = f.read(16)

            actual_ext = detect_format(header)

            results.append(
                {
                    "filepath": filepath,
                    "filename": fname,
                    "current_ext": current_ext_lower,
                    "actual_ext": actual_ext,
                    "mismatch": bool(actual_ext)
                    and actual_ext != EXT_MAP.get(current_ext_lower, ""),
                }
            )
    return results


def fix_files(mismatches: list[dict], dry_run: bool) -> list[tuple[str, str]]:
    """Rename mismatched files. Returns list of (old_path, new_path)."""
    renames = []
    for item in mismatches:
        old_path = item["filepath"]
        base, _ = os.path.splitext(old_path)
        new_path = base + "." + item["actual_ext"]

        if os.path.exists(new_path):
            print(f"  SKIP (target exists): {old_path} -> {new_path}")
            continue

        if not dry_run:
            os.rename(old_path, new_path)

        renames.append((old_path, new_path))
        action = "WOULD RENAME" if dry_run else "RENAMED"
        print(f"  {action}: {old_path} -> {new_path}")

    return renames


def fix_database(db_path: str, renames: list[tuple[str, str]], dry_run: bool) -> int:
    """Update images.local_path in the database. Returns number of updated rows."""
    if not renames:
        return 0

    old_to_new = {}
    for old_path, new_path in renames:
        old_to_new[old_path] = new_path
        old_to_new[old_path.replace("\\", "/")] = new_path.replace("\\", "/")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, local_path FROM images WHERE downloaded = 1 AND local_path IS NOT NULL"
    )
    rows = cur.fetchall()

    updated = 0
    for row_id, local_path in rows:
        normalized = local_path.replace("/", "\\")
        if normalized in old_to_new:
            new_path = old_to_new[normalized]
            if not dry_run:
                cur.execute(
                    "UPDATE images SET local_path = ? WHERE id = ?",
                    (new_path, row_id),
                )
            updated += 1
            action = "WOULD UPDATE" if dry_run else "UPDATED"
            print(
                f"  {action} DB id={row_id}: {os.path.basename(local_path)} -> {os.path.basename(new_path)}"
            )

    if not dry_run:
        conn.commit()
    conn.close()
    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Fix image file extensions based on magic bytes"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying them"
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    data_dir = os.path.join(project_dir, "data", "qq_recorder", "data")
    images_dir = os.path.join(data_dir, "images")
    db_path = os.path.join(data_dir, "recorder.db")

    if not os.path.isdir(images_dir):
        print(f"Images directory not found: {images_dir}")
        sys.exit(1)
    if not os.path.isfile(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Fix Image Extensions ({mode}) ===")
    print(f"Images dir: {images_dir}")
    print(f"Database:   {db_path}")
    print()

    # Step 1: Scan
    print("Scanning image files...")
    all_images = scan_images(images_dir)
    mismatches = [img for img in all_images if img["mismatch"]]
    unknowns = [img for img in all_images if not img["actual_ext"]]

    print(f"  Total images:  {len(all_images)}")
    print(f"  Mismatches:    {len(mismatches)}")
    print(f"  Unknown format: {len(unknowns)}")

    if unknowns:
        print()
        print("  Unknown format files (skipped):")
        for u in unknowns:
            print(f"    {u['filepath']}")

    if not mismatches:
        print()
        print("No mismatches found. All image extensions are correct.")
        return

    print()
    print("Mismatched files:")
    for m in mismatches:
        print(
            f"    {m['filename']}  (current: {m['current_ext']}, actual: .{m['actual_ext']})"
        )

    # Step 2: Fix files
    print()
    print("Fixing file extensions...")
    renames = fix_files(mismatches, args.dry_run)

    # Step 3: Fix database
    print()
    print("Updating database...")
    updated = fix_database(db_path, renames, args.dry_run)

    # Summary
    print()
    print("=== Summary ===")
    print(f"  Files renamed: {len(renames)}")
    print(f"  DB rows updated: {updated}")
    if args.dry_run:
        print("  (dry run - no changes were applied)")


if __name__ == "__main__":
    main()
