# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-02
**Commit:** 6c0fa0e
**Branch:** master
**Stats:** 61 Python files | 5 test files | zero CI

## OVERVIEW

QQContextBot is a two-plugin NcatBot project for recording QQ context and generating
controlled replies from that context. The `qq_recorder` plugin stores group/private
messages to SQLite, downloads and deduplicates images, parses forwards, stickers, and
app shares, and runs scheduled backups. The `qq_grok_reply` plugin reads the recorded
data and generates guarded replies when explicit trigger rules match. Python 3.12+,
async throughout.

Public project name: `QQContextBot`
Code package names: `qq_recorder`, `qq_grok_reply`

## STRUCTURE

```
QQContextBot/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── config.yaml
├── CHANGELOG.md
├── devtools/
│   └── README.md
├── scripts/                   # Export, migration, and backup utilities
├── plugins/
│   ├── qq_recorder/           # Core recorder plugin
│   └── qq_grok_reply/         # Contextual reply plugin
├── start-bot.sh
├── start-bot.ps1
├── napcat/                    # Third-party protocol adapter, do not edit
├── docs/                      # Vendored NcatBot documentation
└── data/qq_recorder/          # Runtime DB + images + backups
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Recorder plugin lifecycle + event registration | `plugins/qq_recorder/plugin.py` | `QQRecorderPlugin` orchestrator |
| Recorder message pipeline | `plugins/qq_recorder/processors.py` | Message/forward/image/app-share flow |
| Recorder commands | `plugins/qq_recorder/commands.py` | stats/recent/search |
| Recorder event conversion | `plugins/qq_recorder/events.py` | `event_to_dict`, `is_command`, formatting |
| Recorder config | `plugins/qq_recorder/config.py` | `RecorderSettings`, monitoring filters |
| Recorder schema | `plugins/qq_recorder/models.py` | ORM tables for messages, images, forwards, replies, mentions, app shares |
| Recorder storage | `plugins/qq_recorder/storage.py` | Async SQLite reads/writes |
| Recorder parsing | `plugins/qq_recorder/message_parser.py` | images, replies, forwards, ats, app shares |
| Recorder image handling | `plugins/qq_recorder/image_handler.py` | download, detect extension, save, dedup |
| Recorder sticker detection | `plugins/qq_recorder/sticker_detector.py` | metadata + text + heuristic cascade |
| Recorder forward parsing | `plugins/qq_recorder/forward_parser.py` | recursive forward node flattening |
| Recorder backups | `plugins/qq_recorder/backup.py` | full/incremental archive and restore chains |
| Reply plugin lifecycle | `plugins/qq_grok_reply/plugin.py` | guarded reply entry point |
| Reply plugin context building | `plugins/qq_grok_reply/context_builder.py` | recorder DB to model context |
| Reply plugin triggers | `plugins/qq_grok_reply/trigger.py` | private, group, prefix, and @ matching |
| Reply plugin sending | `plugins/qq_grok_reply/sender.py` | response split / send helpers |
| Reply plugin model access | `plugins/qq_grok_reply/model_client.py` | AI adapter integration |
| Version history | `CHANGELOG.md` | release notes and manual version tracking |
| Database inspection | `scripts/export_db.py` | summary, schema, search, stats, export |
| Data migrations | `scripts/fix_*.py`, `scripts/migrate_*.py`, `scripts/backfill_*.py` | use `--dry-run` first |
| Tests | `plugins/qq_recorder/tests/`, `plugins/qq_grok_reply/tests/` | recorder + reply coverage |
| Bot startup | `uv run ncatbot run` | loads plugins through `manifest.toml` |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `QQRecorderPlugin` | class | `plugins/qq_recorder/plugin.py` | Recorder plugin entry |
| `BackupManager` | class | `plugins/qq_recorder/backup.py` | Backup/restore scheduler and archive logic |
| `MessageProcessor` | class | `plugins/qq_recorder/processors.py` | Recorder pipeline orchestrator |
| `MessageStorage` | class | `plugins/qq_recorder/storage.py` | All async DB operations |
| `CommandHandler` | class | `plugins/qq_recorder/commands.py` | stats/recent/search commands |
| `parse_message()` | function | `plugins/qq_recorder/message_parser.py` | Segment parsing to DTOs |
| `event_to_dict()` | function | `plugins/qq_recorder/events.py` | Event object to plain dict |
| `combined_detection()` | function | `plugins/qq_recorder/sticker_detector.py` | Sticker confidence pipeline |
| `process_images()` | function | `plugins/qq_recorder/image_handler.py` | Download + format detect + save |
| `detect_extension()` | function | `plugins/qq_recorder/image_handler.py` | URL/content-type/magic-byte cascade |
| `build_config()` | function | `plugins/qq_recorder/config.py` | Config defaults and validation |
| `parse_forward_response()` | function | `plugins/qq_recorder/forward_parser.py` | Recursive forward parsing |
| `extract_app_shares()` | function | `plugins/qq_recorder/message_parser.py` | JSON segment parsing |
| `QQGrokReplyPlugin` | class | `plugins/qq_grok_reply/plugin.py` | Reply plugin entry |
| `build_context()` | function | `plugins/qq_grok_reply/context_builder.py` | Recorded data to context assembly |

## CONVENTIONS

- **Async everywhere**: All network and database I/O is async. Blocking filesystem work should go through `asyncio.to_thread()`.
- **Dataclasses for DTOs**: Use `@dataclass` for config and transfer objects, not Pydantic.
- **Project name vs package names**: The public project is `QQContextBot`; code packages remain `qq_recorder` and `qq_grok_reply` unless a migration is explicitly planned.
- **Config layout**: Root `config.yaml` is NcatBot runtime config. Plugin runtime configs live in `plugins/qq_recorder/config.yaml` and `plugins/qq_grok_reply/config.yaml`.
- **Image detection**: Keep the 3-layer cascade: URL extension -> Content-Type -> magic bytes -> fallback `.jpg`.
- **Deduplication**: Use content MD5, not `file_unique`.
- **Plugin entry**: `manifest.toml` -> `plugin.py` -> `entry_class`. No separate `main.py`.
- **Versioning**: Keep `pyproject.toml`, plugin manifest version, plugin class version, and `CHANGELOG.md` aligned.
- **Build backend**: `pyproject.toml` includes a setuptools build backend for metadata/editable installs. Runtime entry is still `uv run ncatbot run`.
- **Third-party code**: Do not edit `napcat/`.
- **Docs scope**: `docs/` is vendored NcatBot documentation, not QQContextBot-specific content.

## ANTI-PATTERNS

- **NEVER** suppress type errors with `# type: ignore` in new code.
- **NEVER** use empty `except` blocks.
- **NEVER** save all images as `.jpg`.
- **NEVER** block the event loop with sync I/O in the message path.
- **NEVER** modify NcatBot event objects in-place; convert with `event_to_dict()` first.
- **NEVER** rely on `file_unique` for image deduplication.
- **NEVER** rely on `is_sticker` / `stickerId` alone; use `segment_data["sub_type"]`.

## COMMANDS

```bash
uv sync
uv run ncatbot run
uv run ruff check .
uv run ruff format . --diff
uv run pyright
uv run pytest plugins/qq_recorder/tests/ plugins/qq_grok_reply/tests/
python scripts/export_db.py summary
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
```

## NOTES

- `data/qq_recorder/` is the plugin runtime workspace. Paths inside recorder config are relative to that workspace, not the project root.
- `qq_grok_reply.recorder_db` must point at the actual recorder database file via absolute path.
- `qq_recorder` currently uses `QQRecorderPlugin` as its entry class for compatibility.
- Root `config.yaml` may contain secrets in local environments; do not commit credentials.
- Use the plugin-level `AGENTS.md` files when editing one plugin in isolation.
