# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-11
**Version:** 1.3.0
**Author:** Arsvine Zhu

## OVERVIEW

Silent QQ message recorder built on NcatBot framework. Records group/private chat messages to SQLite with image download, forward parsing, and command-based querying. Python 3.12+, async throughout.

## STRUCTURE

```
QQRecorder/
├── config.yaml                # NcatBot main config + plugin-specific config (bot UIN, adapters, plugin loading, monitoring settings)
├── napcat/                    # NapCat protocol adapter (QQ login, WebSocket) - third-party, do not edit
├── data/qq_recorder/          # Runtime data: recorder.db + images/
├── plugins/qq_recorder/       # Core plugin code (see sub-AGENTS.md for details)
├── scripts/                   # Utility scripts
│   ├── export_db.py           # DB inspection/export (summary, schema, search, export)
│   ├── fix_image_extensions.py # Migration: fix .jpg files that are actually GIF/PNG
│   ├── fix_newline_escaping.py # Migration: fix raw newlines in DB
│   ├── fix_image_duplicates.py # Migration: dedup images + add unique constraint
│   ├── migrate_add_is_sticker.py  # Migration: add is_sticker/sticker_confidence columns
│   └── backfill_sticker_flags.py  # Backfill: detect stickers in existing image records
└── pyproject.toml             # Dependencies: ncatbot5, sqlalchemy, aiosqlite, aiohttp
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add message handling logic | `plugins/qq_recorder/processors.py` | MessageProcessor orchestrates the pipeline |
| Add/modify command handlers | `plugins/qq_recorder/commands.py` | CommandHandler: stats/recent/search |
| Change event conversion | `plugins/qq_recorder/events.py` | Pure functions: event_to_dict, is_command |
| Change what gets recorded | `plugins/qq_recorder/config.py` | Targets, image/forward settings |
| Modify DB schema | `plugins/qq_recorder/models.py` | SQLAlchemy models |
| Fix image processing | `plugins/qq_recorder/image_handler.py` | Download, format detection, storage |
| Add/modify sticker detection | `plugins/qq_recorder/sticker_detector.py` | 3-layer cascade: metadata → text → heuristics |
| Adjust plugin config | Root `config.yaml` | `plugin.plugin_configs.qq_recorder` |
| Inspect recorded data | `scripts/export_db.py` | 8 subcommands (summary, search, export…) |
| Bot startup | `uv run ncatbot run` (from project root) | NcatBot loads plugin from plugins/ |

## CONVENTIONS

- **Async everywhere**: All I/O is async (aiohttp, aiosqlite). Blocking ops use `asyncio.to_thread()`.
- **Dataclasses for DTOs**: `@dataclass` for config and transfer objects, not Pydantic.
- **Error isolation**: Message processing catches exceptions per-message; one failure doesn't break the plugin.
- **Image format detection**: 3-layer cascade: URL extension → Content-Type header → magic bytes → fallback `.jpg`.
- **Type hints**: Full type annotations, modern syntax (`list[str]` not `List[str]`, Python 3.12+).
- **Constants**: `ALL_CAPS` for module-level constants, `_leading_underscore` for private helpers.
- **Ruff configuration**: See `ruff.toml` for linting and formatting rules (line length 88, 4-space indent).

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** suppress type errors with `as any` / `# type: ignore`
- **NEVER** use empty `except` blocks — always log or handle
- **NEVER** save all images as `.jpg` — must detect actual format (GIF/PNG/WebP/BMP)
- **NEVER** block the event loop with sync I/O — use `asyncio.to_thread()`
- **NEVER** modify `napcat/` — it's a third-party protocol adapter

## COMMANDS

```bash
# Start the bot
uv run ncatbot run

# Install dependencies
uv sync

# Inspect database
python scripts/export_db.py summary
python scripts/export_db.py search "keyword"
python scripts/export_db.py export -o backup.json

# Fix image extensions (after format detection upgrade)
python scripts/fix_image_extensions.py --dry-run
python scripts/fix_image_extensions.py

# Fix image duplicates (after UniqueConstraint migration)
python scripts/fix_image_duplicates.py --dry-run
python scripts/fix_image_duplicates.py

# Migrate DB: add sticker detection columns
python scripts/migrate_add_is_sticker.py --dry-run
python scripts/migrate_add_is_sticker.py

# Backfill sticker flags for historical images
python scripts/backfill_sticker_flags.py --dry-run
python scripts/backfill_sticker_flags.py
python scripts/backfill_sticker_flags.py --start-id 100 --end-id 200
```

## NOTES

- Single config file: root `config.yaml` contains both NcatBot framework configuration **and** plugin-specific configuration under `plugin.plugin_configs.qq_recorder`.
- Images stored by date: `data/qq_recorder/data/images/YYYY/MM/DD/<md5hash>.<ext>`. Filename is content MD5 (auto-dedup).
- `file_unique` field in images table is always `"0"` — QQ doesn't always provide it. MD5 hash is used instead.
- DB path in config is relative to plugin workspace (`data/qq_recorder/`), not project root.
- NapCat directory contains login scripts and protocol binaries — don't edit unless upgrading NapCat.

---

## NcatBot AI Agent Reference

This project is built on the NcatBot framework. All framework-level development questions should refer to the following documentation:

### Directory Overview

| Path | Description |
|------|-------------|
| `.agents/skills/` | AI Agent skill files, pre-loaded for your use |
| `docs/docs/examples/` | Example code (qq / github / cross_platform / common …) |
| `docs/docs/notes/guide/` | Getting started to advanced usage guides |
| `docs/docs/notes/reference/` | API reference documentation for all modules |

### Core Skills

| Skill | Path | Purpose |
|-------|------|---------|
| framework-usage | `.agents/skills/framework-usage/SKILL.md` | Developing bots with NcatBot: plugin registration, event handling, message sending, CLI debugging |
| testing-framework | `.agents/skills/testing-framework/SKILL.md` | Writing and running plugin tests |
| plugin-migration | `.agents/skills/plugin-migration/SKILL.md` | Migrating 4.x plugins to 5.0 |
| code-nav | `.agents/skills/code-nav/SKILL.md` | Locating code implementations in this project |
| codebase-nav | `.agents/skills/codebase-nav/SKILL.md` | Navigating this project's codebase to understand structure |

> **AI Agent Note**: When encountering NcatBot framework-related development questions, always invoke the corresponding skill first to get complete instructions — don't develop from memory.

### Key Documentation Entries

- `docs/docs/notes/guide/README.md` — Guide index (quick start, plugin development, message sending...)
- `docs/docs/notes/reference/README.md` — API reference index (lookup classes/methods by purpose)
- `docs/docs/examples/README.md` — Example index (sorted by platform and difficulty)

### External Links

- Documentation: <https://docs.ncatbot.top>
- GitHub: <https://github.com/ncatbot/NcatBot>
