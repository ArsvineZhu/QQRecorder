# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-08
**Version:** 1.1.3
**Author:** Arsvine Zhu

## OVERVIEW

Silent QQ message recorder built on NcatBot framework. Records group/private chat messages to SQLite with image download, forward parsing, and command-based querying. Python 3.12+, async throughout.

## STRUCTURE

```
QQRecorder/
├── recorder/                  # NcatBot working directory (run bot from here)
│   ├── config.yaml            # Plugin-specific config (monitoring, storage, image settings)
│   ├── napcat/                # NapCat protocol adapter (QQ login, WebSocket)
│   ├── data/qq_recorder/      # Runtime data: recorder.db + images/
│   └── plugins/qq_recorder/   # Core plugin code (see sub-AGENTS.md)
├── scripts/                   # Utility scripts
│   ├── export_db.py           # DB inspection/export (summary, schema, search, export)
│   └── fix_image_extensions.py # Migration: fix .jpg files that are actually GIF/PNG
├── config.yaml                # NcatBot main config (bot UIN, adapters, plugin loading)
└── pyproject.toml             # Dependencies: ncatbot5, sqlalchemy, aiosqlite, aiohttp
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add message handling logic | `recorder/plugins/qq_recorder/plugin.py` | Event handlers + command routing |
| Change what gets recorded | `recorder/plugins/qq_recorder/config.py` | Targets, image/forward settings |
| Modify DB schema | `recorder/plugins/qq_recorder/models.py` | SQLAlchemy models |
| Fix image processing | `recorder/plugins/qq_recorder/image_handler.py` | Download, format detection, storage |
| Adjust plugin config | `recorder/config.yaml` | `plugin.plugin_configs.qq_recorder` |
| Inspect recorded data | `scripts/export_db.py` | 8 subcommands (summary, search, export…) |
| Bot startup | `cd recorder && python -m ncatbot` | NcatBot loads plugin from plugins/ |

## CONVENTIONS

- **Async everywhere**: All I/O is async (aiohttp, aiosqlite). Blocking ops use `asyncio.to_thread()`.
- **Dataclasses for DTOs**: `@dataclass` for config and transfer objects, not Pydantic.
- **Error isolation**: Message processing catches exceptions per-message; one failure doesn't break the plugin.
- **Image format detection**: 3-layer cascade: URL extension → Content-Type header → magic bytes → fallback `.jpg`.
- **Type hints**: Full type annotations, modern syntax (`list[str]` not `List[str]`, Python 3.12+).
- **Constants**: `ALL_CAPS` for module-level constants, `_leading_underscore` for private helpers.
- **No ruff config file**: ruff is a dependency but no `ruff.toml` exists — uses defaults.

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** suppress type errors with `as any` / `# type: ignore`
- **NEVER** use empty `except` blocks — always log or handle
- **NEVER** save all images as `.jpg` — must detect actual format (GIF/PNG/WebP/BMP)
- **NEVER** block the event loop with sync I/O — use `asyncio.to_thread()`
- **NEVER** modify `recorder/napcat/` — it's a third-party protocol adapter

## COMMANDS

```bash
# Start the bot
cd recorder && python -m ncatbot

# Install dependencies
uv sync

# Inspect database
python scripts/export_db.py summary
python scripts/export_db.py search "keyword"
python scripts/export_db.py export -o backup.json

# Fix image extensions (after format detection upgrade)
python scripts/fix_image_extensions.py --dry-run
python scripts/fix_image_extensions.py
```

## NOTES

- Two config files: root `config.yaml` (NcatBot framework) and `recorder/config.yaml` (plugin-specific). Don't confuse them.
- Plugin config lives under `plugin.plugin_configs.qq_recorder` in `recorder/config.yaml`, not in a separate file.
- Images stored by date: `data/images/YYYY/MM/DD/<md5hash>.<ext>`. Filename is content MD5 (auto-dedup).
- `file_unique` field in images table is always `"0"` — QQ doesn't always provide it. MD5 hash is used instead.
- DB path in config is relative to plugin workspace (`recorder/data/qq_recorder/`), not project root.
- NapCat directory contains login scripts and protocol binaries — don't edit unless upgrading NapCat.
