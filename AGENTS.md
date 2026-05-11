# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-11
**Commit:** 9ef0952
**Branch:** master
**Stats:** ~22 Python files, ~7,900 lines | 1 test file, ~6% coverage | Zero CI/CD

## OVERVIEW

Silent QQ message recorder built on NcatBot framework. Records group/private chat messages to SQLite with image download, forward parsing, sticker detection, and command-based querying. Python 3.12+, async throughout. **No build system, no CI/CD, no console_scripts entry points** — run exclusively via `uv run ncatbot run` as an NcatBot plugin.

## STRUCTURE

```
QQRecorder/
├── config.yaml                # NcatBot framework config + plugin-specific config under plugin.plugin_configs.qq_recorder
├── pyproject.toml             # Project metadata + dependencies (ncatbot5, sqlalchemy, aiosqlite, aiohttp)
├── ruff.toml                  # Linting/formatting rules (88 chars, double-quote, E/W/F/B/I/C/UP)
├── pyrightconfig.json         # Type checker config: targets plugins/ + scripts/, Python 3.12
├── README.md                  # User-facing docs (N.B.: "项目结构" section is outdated, shows non-existent recorder/ prefix)
├── plugins/qq_recorder/       # Core plugin code (see sub-AGENTS.md for details)
├── scripts/                   # Standalone CLI tools (migration + DB inspection)
│   ├── export_db.py           # 8 subcommands: summary, schema, search, stats, export…
│   ├── fix_image_extensions.py # Migration: fix .jpg files that are actually GIF/PNG
│   ├── fix_newline_escaping.py # Migration: fix raw newlines in DB
│   ├── fix_image_duplicates.py # Migration: dedup images + add unique constraint
│   ├── migrate_add_is_sticker.py  # Migration: add is_sticker/sticker_confidence columns
│   └── backfill_sticker_flags.py  # Backfill: detect stickers in existing image records
├── napcat/                    # Vendored NapCat protocol adapter (.bat/.exe/.dll/node_modules) — third-party, do NOT edit
├── docs/                      # Vendored NcatBot framework documentation (VuePress project) — not project-specific
├── .agents/skills/            # NcatBot framework AI agent skills — not project-specific
└── data/qq_recorder/          # Runtime data: recorder.db + images/YYYY/MM/DD/
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Plugin lifecycle + event registration | `plugins/qq_recorder/plugin.py` | QQRecorderPlugin (thin orchestrator, 77 lines) |
| Add message handling logic | `plugins/qq_recorder/processors.py` | MessageProcessor: message/forward/image pipeline |
| Add/modify command handlers | `plugins/qq_recorder/commands.py` | CommandHandler: stats/recent/search |
| Change event conversion | `plugins/qq_recorder/events.py` | Pure functions: event_to_dict, is_command, format_stored_log |
| Change what gets recorded | `plugins/qq_recorder/config.py` | RecorderSettings, is_chat_monitored |
| Modify DB schema | `plugins/qq_recorder/models.py` | SQLAlchemy ORM: Message, Image, ForwardMessage, Reply, AtMention |
| Async DB operations | `plugins/qq_recorder/storage.py` | MessageStorage: all SQLite read/write |
| Parse message segments | `plugins/qq_recorder/message_parser.py` | parse_message → ParsedMessage (images, replies, forwards, ats) |
| Fix image processing | `plugins/qq_recorder/image_handler.py` | Download, format detection, MD5-dedup storage |
| Add/modify sticker detection | `plugins/qq_recorder/sticker_detector.py` | 3-layer cascade: metadata → text → heuristics |
| Forward message parsing | `plugins/qq_recorder/forward_parser.py` | Recursive forward node parsing |
| Text escaping/unescaping | `plugins/qq_recorder/text_utils.py` | Control char escape for DB storage |
| Adjust plugin config | Root `config.yaml` | `plugin.plugin_configs.qq_recorder` |
| Inspect recorded data | `scripts/export_db.py` | 8 subcommands (summary, search, export…) |
| Run data migrations | `scripts/fix_*.py`, `scripts/migrate_*.py`, `scripts/backfill_*.py` | All support `--dry-run` |
| Test sticker detection | `plugins/qq_recorder/tests/test_sticker_detection.py` | 8 unit tests (only test file in project) |
| NcatBot framework APIs | `docs/docs/notes/reference/` | Vendored framework reference docs |
| Bot startup | `uv run ncatbot run` (from project root) | NcatBot loads plugin via manifest.toml |

## CODE MAP

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `QQRecorderPlugin` | class | `plugins/qq_recorder/plugin.py:14` | Plugin entry: lifecycle + 4 event handlers |
| `MessageProcessor` | class | `plugins/qq_recorder/processors.py` | Message pipeline orchestrator |
| `MessageStorage` | class | `plugins/qq_recorder/storage.py:15` | All async DB operations |
| `CommandHandler` | class | `plugins/qq_recorder/commands.py` | stats/recent/search subcommands |
| `parse_message()` | function | `plugins/qq_recorder/message_parser.py` | Segment parsing → ParsedMessage DTO |
| `event_to_dict()` | function | `plugins/qq_recorder/events.py` | Event object → dict (manual field extraction) |
| `combined_detection()` | function | `plugins/qq_recorder/sticker_detector.py` | 3-layer sticker confidence pipeline |
| `process_images()` | function | `plugins/qq_recorder/image_handler.py` | Download + format detect + save |
| `detect_extension()` | function | `plugins/qq_recorder/image_handler.py` | 3-layer cascade → file extension |
| `build_config()` | function | `plugins/qq_recorder/config.py` | Config defaults + validation |
| `parse_forward_response()` | function | `plugins/qq_recorder/forward_parser.py` | Recursive forward node parsing |

## CONVENTIONS

- **Async everywhere**: All I/O is async (aiohttp, aiosqlite). Blocking ops use `asyncio.to_thread()`.
- **Dataclasses for DTOs**: `@dataclass` for config and transfer objects, not Pydantic.
- **Error isolation**: Message processing catches exceptions per-message; one failure doesn't break the plugin.
- **Image format detection**: 3-layer cascade — URL extension → Content-Type header → magic bytes → fallback `.jpg`. Never skip a layer.
- **Type hints**: Full type annotations, modern syntax (`list[str]` not `List[str]`, Python 3.12+).
- **Constants**: `ALL_CAPS` for module-level constants, `_leading_underscore` for private helpers.
- **Linting**: Ruff — rules E, W, F, B, I, C, UP; line length 88; 4-space indent; double quotes.
- **Type checking**: Pyright targeting `plugins/` + `scripts/` (Python 3.12). Excludes `napcat/`, `.venv/`.
- **Package manager**: `uv` (`uv sync`, `uv run`). lockfile committed.
- **No build system**: No `[build-system]` in pyproject.toml. Not pip-installable or PyPI-published. Plugin-only runtime.
- **No console_scripts**: Entry exclusively via `uv run ncatbot run`. Plugin loaded dynamically by NcatBot.
- **Plugin entry**: `manifest.toml` → `main = "plugin.py"` → `entry_class = "QQRecorderPlugin"`. No separate `main.py`.
- **Image storage**: `data/qq_recorder/data/images/YYYY/MM/DD/<md5hash>.<ext>`. Content MD5 dedup.
- **CLI script convention**: All scripts use `argparse` + `--dry-run` flag + `if __name__ == "__main__"` guard.
- **Sticker detection**: Invoked inside `extract_images()` in message_parser.py — no separate pipeline step. Confidence ≥ 0.7 → sticker.
- **Config is single-file**: Root `config.yaml` holds both NcatBot framework config and plugin config under `plugin.plugin_configs.qq_recorder`.

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** suppress type errors with `as any` / `# type: ignore` (note: legacy `# pyright: ignore[...]` exists in storage.py, image_handler.py — refactor out, do not add more)
- **NEVER** use empty `except` blocks — always log or handle
- **NEVER** save all images as `.jpg` — must detect actual format (GIF/PNG/WebP/BMP)
- **NEVER** block the event loop with sync I/O — use `asyncio.to_thread()`
- **NEVER** modify `napcat/` — it's a third-party protocol adapter
- **NEVER** hardcode `.jpg` as image extension — always use `detect_extension()` cascade
- **NEVER** access `self.api` before `on_load()` completes — API available only after plugin init
- **NEVER** modify event objects in-place — convert to dict via `event_to_dict()` first
- **NEVER** rely on `is_sticker`/`stickerId` fields — use `sub_type` in segment_data (0=image, 1=sticker, 7=shop, 13=emoji)
- **NEVER** use `file_unique` for image dedup — it's always `"0"` from QQ. Use MD5 hash of content.
- **NEVER** add sync I/O in the message processing path — all blocking calls must go through `asyncio.to_thread()`

## COMMANDS

```bash
# ---- Setup ----
uv sync                                    # Install all dependencies
uv run ncatbot run                         # Start the bot

# ---- Quality ----
uv run ruff check .                        # Lint check
uv run ruff format . --diff                # Format check (dry-run)
uv run ruff format .                       # Auto-format
uv run pyright                             # Type check
uv run pytest plugins/qq_recorder/tests/   # Run tests (only sticker_detector)

# ---- Database inspection ----
python scripts/export_db.py summary        # Overview: row counts, time range, type stats
python scripts/export_db.py schema         # Table schema: columns, types, constraints, indexes
python scripts/export_db.py search "关键词" # Search message content (max 10 results)
python scripts/export_db.py messages --chat group --id 1072706649  # Messages filtered by type/ID
python scripts/export_db.py images --downloaded                      # Downloaded images
python scripts/export_db.py images --missing                         # Missing images
python scripts/export_db.py stats                                    # Per-chat stats
python scripts/export_db.py export -o backup.json                    # Full DB export (JSON)
python scripts/export_db.py export --format csv -o backup.csv        # Full DB export (CSV)

# ---- Migration scripts (always --dry-run first!) ----
python scripts/fix_image_extensions.py --dry-run
python scripts/fix_newline_escaping.py --dry-run
python scripts/fix_image_duplicates.py --dry-run
python scripts/migrate_add_is_sticker.py --dry-run
python scripts/backfill_sticker_flags.py --dry-run
python scripts/backfill_sticker_flags.py --start-id 100 --end-id 200  # Batch backfill
```

## NOTES

- Single config file: root `config.yaml` contains both NcatBot framework configuration **and** plugin-specific configuration under `plugin.plugin_configs.qq_recorder`. No secondary `recorder/config.yaml` exists — README references an outdated structure.
- Images stored by date: `data/qq_recorder/data/images/YYYY/MM/DD/<md5hash>.<ext>`. Filename is content MD5 (auto-dedup).
- `file_unique` field in images table is always `"0"` — QQ doesn't provide it. MD5 hash is used for dedup. Use `file_url` for querying.
- DB path in config is relative to plugin workspace (`data/qq_recorder/`), not project root.
- `ruff` is listed as a RUNTIME dependency in `pyproject.toml` (not dev-only) — this is non-standard. If refactoring, consider moving to `[dependency-groups].dev`.
- NapCat directory contains login scripts and protocol binaries — don't edit unless upgrading NapCat.
- `docs/` is a vendored copy of the NcatBot framework documentation site (VuePress). Not QQRecorder-specific docs. Gitignored.
- `.agents/skills/` are NcatBot framework AI agent instructions. Not QQRecorder-specific. Load them for framework-related dev questions.
- Tests: only `test_sticker_detection.py` exists (8 tests, ~6% coverage). No conftest.py, fixtures, or mocks. No CI enforcement.
- `# pyright: ignore[reportOptionalCall]` exists in legacy code (storage.py, image_handler.py, processors.py). Do not add more.
- `ForwardMessage` is self-referential (`parent_forward_id` FK → self) — tree stored as adjacency list.
- Forward IDs from parsed messages may be empty/whitespace — always filter before calling API.

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
