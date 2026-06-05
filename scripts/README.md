# Tool Scripts

This directory contains standalone maintenance tools for QQContextBot.

## Safety First

- Run migration scripts with `--dry-run` first.
- Stop the bot before running restore operations.
- Paths inside the recorder plugin usually resolve under `data/qq_recorder/`.

## Database Inspection

`scripts/export_db.py` reads the recorder SQLite database and prints summaries,
schema details, searchable message rows, image records, statistics, or full export
payloads.

Examples:

```bash
python scripts/export_db.py summary
python scripts/export_db.py schema
python scripts/export_db.py search "关键词"
python scripts/export_db.py messages --chat group --id 1072706649
python scripts/export_db.py images --downloaded
python scripts/export_db.py stats
python scripts/export_db.py export -o backup.json
python scripts/export_db.py export --format csv -o backup.csv
```

## Backups

`scripts/backup_tool.py` lists backup archives and restores a backup chain.

Examples:

```bash
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
python scripts/backup_tool.py restore \
  --archive <backup.zip> \
  --db-path <recorder.db> \
  --images-dir <images-dir>
```

`restore` checks whether the bot/runtime still appears active unless `--force` is
provided.

## Migrations and Backfills

These scripts change database content or file paths. Always review the dry-run output
before applying them:

```bash
python scripts/fix_image_extensions.py --dry-run
python scripts/fix_newline_escaping.py --dry-run
python scripts/fix_image_duplicates.py --dry-run
python scripts/migrate_add_is_sticker.py --dry-run
python scripts/migrate_add_app_share.py --dry-run
python scripts/backfill_sticker_flags.py --dry-run
python scripts/backfill_sticker_flags.py --start-id 100 --end-id 200
python scripts/backfill_recorder_media_history.py --dry-run
```

## Notes

- `fix_image_extensions.py` corrects image suffixes from real file contents.
- `fix_newline_escaping.py` normalizes stored text fields for single-line output.
- `fix_image_duplicates.py` deduplicates image rows before rebuilding the unique
  constraint.
- `migrate_add_is_sticker.py` adds sticker metadata columns to the images table.
- `migrate_add_app_share.py` adds app-share storage columns and tables.
- `backfill_sticker_flags.py` runs the real sticker detector against stored image
  records.
- `backfill_recorder_media_history.py` backfills recoverable bot messages from
  trace tables and regenerates missing `semantic_text` for stored media analyses.
