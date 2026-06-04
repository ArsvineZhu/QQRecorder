# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-04
**Branch:** feat/agent-runtime

## OVERVIEW

QQContextBot is a **three-plugin** NcatBot project for recording QQ context and generating
controlled replies from that context.

| Plugin | Directory | Role |
|--------|-----------|------|
| `qq_recorder` | `plugins/qq_recorder/` | Store group/private messages to SQLite; download images; parse forwards/stickers/app-shares; scheduled backups |
| `qq_grok_reply` | `plugins/qq_grok_reply/` | Lighter two-round reply plugin — single `request_more_context` tool, topic-aware context |
| `grok` | `plugins/grok/` | Modern multi-tool Agent reply plugin — 6 tools, JSON profile store, vision, thinking mode |

Python 3.12+, async throughout.

## STRUCTURE

```
QQContextBot/
├── config.yaml              # NcatBot runtime config (adapters, plugin loader)
├── pyproject.toml
├── README.md
├── AGENTS.md                # Project-level AI maintenance docs
├── CHANGELOG.md
├── plugins/
│   ├── qq_recorder/         # Core recorder (8 ORM tables)
│   ├── qq_grok_reply/       # Lightweight reply plugin
│   └── grok/                # Multi-tool Agent reply plugin (formerly qq_agent_reply)
├── scripts/                 # Export, migration, backup utilities
├── data/qq_recorder/        # Runtime DB + images + backups
├── napcat/                  # Third-party protocol adapter, do not edit
└── docs/                    # Vendored NcatBot documentation
```

## PLUGIN OVERVIEWS

### qq_recorder (always-on)

Records all QQ group/private messages into SQLite. Handles images (download, dedup, format
detect), merge-forwards (recursive parsing + flattening), stickers, app shares, replies,
and @-mentions. Supports scheduled backup/restore (full + incremental).

Tables: `messages`, `message_segments`, `images`, `replies`, `forward_messages`,
`at_mentions`, `app_shares`, `monitored_chats`, `image_analyses`.

### qq_grok_reply (optional, lightweight)

Two-round reply plugin with a single `request_more_context` tool. Reads recorder DB via
`RecorderBridge`, builds topic-aware or recent-message context, calls LiteLLM via NcatBot's
`api.ai.chat()`, and sends split responses. Includes vision analysis (DashScope), cooldown
tracking, and TraceStore persistence.

### grok (optional, full-featured)

Multi-turn Agent reply plugin. On each turn the model may call any of the 6 registered
tools. Tools are validated through a `ToolRegistry` with strict JSON schemas.

**Tools**: `track_reply`, `load_context`, `extract_forward`, `read_picture`, `read_video`,
`load_profile`, `create_profile`, `update_profile`, `delete_profile`.

Key differences from `qq_grok_reply`:
- Multi-turn loop (not fixed two-round) — model decides when to stop
- Profile system: JSON file (`profiles.json`), auto-create on first contact
- Thinking mode support via `extra_body` + `reasoning_effort`
- Per-group nicknames stored in `group_nicknames[chat_id]`
- `ImageAnalysis` table in recorder DB for permanent vision result storage
- Ban/unban detection with `handle_group_ban()` → profile mute state + recorder notice

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Recorder entry + lifecycle | `plugins/qq_recorder/plugin.py` | `QQRecorderPlugin` |
| Recorder message pipeline | `plugins/qq_recorder/processors.py` | Message/forward/image/app-share flow |
| Recorder commands | `plugins/qq_recorder/commands.py` | stats/recent/search |
| Recorder ORM schema | `plugins/qq_recorder/models.py` | 9 tables including `ImageAnalysis` |
| Recorder storage | `plugins/qq_recorder/storage.py` | `MessageStorage` — includes `save_image_analysis()` |
| Recorder forward parsing | `plugins/qq_recorder/forward_parser.py` | `extract_text_from_content()` with segment labels |
| Recorder backups | `plugins/qq_recorder/backup.py` | Full/incremental archive + restore |
| Grok plugin entry | `plugins/grok/plugin.py` | `GrokPlugin` — thin event routing |
| Grok event orchestration | `plugins/grok/app/orchestrator.py` | `handle_event()` — main pipeline |
| Grok profile tools | `plugins/grok/tools/profile_tools.py` | CRUD profile tools, JSON store |
| Grok context tools | `plugins/grok/tools/context_tools.py` | track_reply, load_context, extract_forward |
| Grok media tools | `plugins/grok/tools/media_tools.py` | read_picture, read_video |
| Grok tool registry | `plugins/grok/tools/registry.py` | `ToolRegistry` — validation + execution |
| Grok runtime loop | `plugins/grok/app/runtime.py` | `AgentRuntime` — multi-turn loop |
| Grok model adapter | `plugins/grok/agent/model_adapter.py` | `run_agent_turn()` + thinking mode |
| Grok trigger rules | `plugins/grok/trigger/rules.py` | prefilter, cooldown, final decision |
| Grok ban handler | `plugins/grok/app/ban_handler.py` | `handle_group_ban()` — mute state |
| Grok profile JSON store | `plugins/grok/infra/profile_json_store.py` | Single-file JSON persistence |
| Grok trace store | `plugins/grok/infra/trace_store.py` | `AgentTraceStore` |
| Grok vision pipeline | `plugins/grok/vision/` | analyzer, cache, quota, schemas |
| Grok config | `plugins/grok/config/` | `schema.py`, `builder.py`, `validation.py` |
| Grok system prompt | `plugins/grok/prompt/system.md` | ~200-line Chinese system prompt |
| Grok tests | `plugins/grok/tests/` | 25 tests across all modules |
| Grok JSON schemas | `plugins/grok/schemas/tools/*.json` | 9 tool schemas |

## GROK PLUGIN DATA FLOW

```
NcatBot Event → GrokPlugin.on_group_message()
  → trigger.prefilter_event()        # cheap gate (enabled, target, prefix/@)
  → bridge.wait_until_visible()      # read-after-write retry
  → trigger.final_decision()         # cooldown, reply-to-bot
  → trace_store.insert_trace()
  → profile_json_store.upsert_profile()    # auto-create blank profile for new users
  → AgentRuntime.run()                # multi-turn loop (≤max_steps):
      ├── run_agent_turn()            # call LLM with tools
      ├── tool calls? → execute(registry) → append evidence
      └── no tool calls? → text response done
  → delivery.send_reply()             # split + send
  → trace_store.finish_trace()
```

## JSON PROFILE STORE

File: `<workspace>/data/profiles.json` (configurable via `profile.db_path`)

```json
{
  "version": 1,
  "users": {
    "2162371684": {
      "username": "Zodiac",
      "preferred_name": "Arsvine",
      "group_nicknames": { "1101497265": "阿梓" },
      "group_instruction": "技术问题先给结论",
      "language_style": "简洁直接",
      "habit_preferences": ["少客套"],
      "muted_until": 1749123456,
      "muted_group": "1101497265"
    }
  }
}
```

## IMAGE ANALYSIS PERSISTENCE

When `read_picture` or `read_video` analyze content, results are written to both:

| Store | Table | TTL | Purpose |
|-------|-------|-----|---------|
| `VisionCacheStore` | `vision_cache` | `cache_ttl_days` | Fast lookup, avoid re-API |
| `MessageStorage` | `image_analyses` | Permanent | Per-user recall, system notices |

Ban/unban events are also written as `media_type="system_notice"` entries in `image_analyses`.

## CONVENTIONS

- **Async everywhere**: All network and database I/O is async. Blocking filesystem work
  should go through `asyncio.to_thread()`.
- **Dataclasses for DTOs**: Use `@dataclass` for config and transfer objects, not Pydantic.
- **Config layout**: Root `config.yaml` is NcatBot runtime (adapters). Plugin configs in
  `plugins/*/config.yaml`.
- **Image detection**: 3-layer cascade: URL extension → Content-Type → magic bytes → `.jpg`.
- **Deduplication**: Use content MD5, not `file_unique`.
- **Plugin entry**: `manifest.toml` → `plugin.py` → `entry_class`.
- **Versioning**: Keep `pyproject.toml`, plugin manifest version, plugin class version,
  and `CHANGELOG.md` aligned.
- **Build backend**: setuptools via `pyproject.toml`. Runtime: `uv run ncatbot run`.
- **Business logic separation**: `plugin.py` is thin event routing only. Business logic
  lives in `app/`, `tools/`, `trigger/` modules.
- **Cross-plugin access**: `grok` reads `qq_recorder` DB via `RecorderBridge` (dynamic
  import via `compat.py`). Never import recorder models directly.
- **Third-party code**: Do not edit `napcat/`.
- **Docs scope**: `docs/` is vendored NcatBot documentation, not project-specific.

## ANTI-PATTERNS

- **NEVER** suppress type errors with `# type: ignore` in new code.
- **NEVER** use empty `except` blocks.
- **NEVER** save all images as `.jpg`.
- **NEVER** block the event loop with sync I/O in the message path.
- **NEVER** modify NcatBot event objects in-place; convert with `event_to_dict()` first.
- **NEVER** rely on `file_unique` for image deduplication.
- **NEVER** rely on `is_sticker` / `stickerId` alone; use `segment_data["sub_type"]`.
- **NEVER** add business logic in `plugin.py` — use `app/`, `tools/`, or `trigger/` modules.
- **NEVER** call `get_forward_msg` for forward content — read from recorder DB instead.

## COMMANDS

```bash
uv sync
uv run ncatbot run
uv run ruff check plugins/
uv run ruff format plugins/ --check
uv run pyright plugins/
uv run pytest plugins/grok/tests/ plugins/qq_recorder/tests/ plugins/qq_grok_reply/tests/
python scripts/export_db.py summary
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
```

## NOTES

- `data/qq_recorder/` is the recorder plugin runtime workspace. Paths in recorder config
  are relative to that workspace.
- `grok` plugin name in config is `grok` (dir), `GrokPlugin` (class), `"grok"` (manifest).
- Profile data is managed in JSON (`data/profiles.json`), not in `config.yaml`.
- Thinking mode: set `thinking_enabled: true` + `thinking_effort: high` in model config.
  Passed as `extra_body={"thinking": {"type": "enabled"}}` + `reasoning_effort`.
- Forward message API (`get_forward_msg`) is unreliable for expired messages.
  `extract_forward` always reads from recorder DB.
- Root `config.yaml` may contain secrets in local environments; do not commit credentials.
