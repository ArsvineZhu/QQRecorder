# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-06
**Branch:** codex/grok-context-system-upgrade

## OVERVIEW

QQContextBot is a **two-plugin** NcatBot project for recording QQ context and generating
controlled replies from that context.

| Plugin | Directory | Role |
|--------|-----------|------|
| `qq_recorder` | `plugins/qq_recorder/` | Store group/private messages to SQLite; download images; parse forwards/stickers/app-shares; scheduled backups |
| `grok` | `plugins/grok/` | Multi-turn Agent reply plugin — 14 tool schemas, JSON profile store, vision, thinking mode, ban detection |

Python 3.12+, async throughout. 130 tests across both plugins.

## STRUCTURE

```
QQContextBot/
├── config.yaml              # NcatBot runtime config (adapters, plugin loader)
├── pyproject.toml
├── README.md
├── AGENTS.md                # Project-level AI maintenance docs
├── CHANGELOG.md
├── plugins/
│   ├── qq_recorder/         # Core recorder (10 ORM tables)
│   └── grok/                # Multi-tool Agent reply plugin
├── scripts/                 # Export, migration, backup utilities
├── data/
│   ├── qq_recorder/         # Runtime DB + images + backups
│   └── grok/                # Runtime profiles.json
├── napcat/                  # Third-party protocol adapter, do not edit
└── docs/                    # Vendored NcatBot documentation
```

## PLUGIN OVERVIEWS

### qq_recorder (always-on)

Records all QQ group/private messages into SQLite. Handles images (download, dedup, format
detect), merge-forwards (recursive parsing with 3-tier fallback), stickers, app shares,
replies, @-mentions, and videos. Supports scheduled backup/restore (full + incremental).

Tables: `messages`, `message_segments`, `images`, `videos`, `replies`, `forward_messages`,
`at_mentions`, `app_shares`, `monitored_chats`, `image_analyses`.

Forward parsing falls back through: API (`get_forward_msg`) → CQ-embedded JSON content
(URL+HTML decoded) → inline `node` segments in the event message array (for newer NapCat).

Newlines in all log output are escaped via `_LineSafeFormatter` wrapping root handlers.

### grok (optional, full-featured)

Multi-turn Agent reply plugin with 14 tool schemas (9 registered handler tools + 5
meta/internal). On each turn the model may call any registered tool. Tools are validated
through a `ToolRegistry` with strict JSON schemas.

**Registered tools**: `track_reply`, `load_context`, `load_message`, `extract_forward`,
`read_picture`, `read_video`, `load_profile`, `create_profile`, `update_profile`,
`delete_profile`, `query_chat_history`, `load_tool_guide`, `terminate`.

Key features:
- Multi-turn loop (model decides when to stop, `max_steps: 12`)
- Profile system: JSON file (`data/grok/profiles.json`), auto-create on first contact
- Thinking mode support via `extra_body` + `reasoning_effort`
- `ImageAnalysis` table in recorder DB for permanent vision result storage
- Ban/unban detection → profile mute state + recorder notice
- Reply-to-bot detection with quick-gate (`_has_reply_segment`) before read-after-write wait
- `_LineSafeFormatter` for all grok log output

The orchestrator (`orchestrator.py`) includes a fast-path gate: if prefilter rejects and the
message has no `reply` segment, it skips the expensive `wait_until_visible()` entirely.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Recorder entry + lifecycle | `plugins/qq_recorder/plugin.py` | `QQRecorderPlugin` |
| Recorder message pipeline | `plugins/qq_recorder/processors.py` | Message/forward/image/app-share flow |
| Recorder commands | `plugins/qq_recorder/commands.py` | stats/recent/search |
| Recorder ORM schema | `plugins/qq_recorder/models.py` | 10 tables including `ImageAnalysis` |
| Recorder storage | `plugins/qq_recorder/storage.py` | `MessageStorage` — includes `save_image_analysis()` |
| Recorder forward parsing | `plugins/qq_recorder/forward_parser.py` | `parse_forward_response`, `parse_forward_embed`, `parse_forward_nodes` |
| Recorder message parsing | `plugins/qq_recorder/message_parser.py` | segment extractors, `extract_inline_forward_nodes` |
| Recorder log formatting | `plugins/qq_recorder/events.py` | `format_stored_log`, `_build_extras_tags` |
| Recorder text escaping | `plugins/qq_recorder/text_utils.py` | `escape_text`, `unescape_text` |
| Recorder backups | `plugins/qq_recorder/backup.py` | Full/incremental archive + restore |
| Recorder data migration | `plugins/qq_recorder/backfill.py` | Vision result backfill (imports from grok) |
| Grok plugin entry | `plugins/grok/plugin.py` | `GrokPlugin` — thin event routing |
| Grok event orchestration | `plugins/grok/app/orchestrator.py` | `handle_event()` — main pipeline |
| Grok context tools | `plugins/grok/tools/context_tools.py` | `track_reply`, `load_context`, `load_message`, `extract_forward` |
| Grok profile tools | `plugins/grok/tools/profile_tools.py` | CRUD profile tools, JSON store |
| Grok media tools | `plugins/grok/tools/media_tools.py` | `read_picture`, `read_video` |
| Grok history tools | `plugins/grok/tools/history_tools.py` | `query_chat_history` |
| Grok guide tools | `plugins/grok/tools/guide_tools.py` | `load_tool_guide`, `terminate` |
| Grok tool registry | `plugins/grok/tools/registry.py` | `ToolRegistry` — validation + execution |
| Grok runtime loop | `plugins/grok/app/runtime.py` | `AgentRuntime` — multi-turn loop |
| Grok model adapter | `plugins/grok/agent/model_adapter.py` | `run_agent_turn()` + thinking mode |
| Grok prompt builder | `plugins/grok/prompt_synthesizer/` | `build_model_messages`, `render_system_prompt` |
| Grok system prompt template | `plugins/grok/prompt/system.md` | Chinese system prompt |
| Grok tool JSON schemas | `plugins/grok/schemas/tools/*.json` | 14 tool schemas |
| Grok trigger rules | `plugins/grok/trigger/rules.py` | prefilter, cooldown, final decision |
| Grok ban handler | `plugins/grok/app/ban_handler.py` | `handle_group_ban()` — mute state |
| Grok profile JSON store | `plugins/grok/infra/profile_json_store.py` | Single-file JSON persistence |
| Grok trace store | `plugins/grok/infra/trace_store.py` | `AgentTraceStore` |
| Grok conversation store | `plugins/grok/infra/conversation_store.py` | Multi-turn transcript persistence |
| Grok recorder bridge | `plugins/grok/infra/recorder_bridge.py` | `RecorderBridge` — cross-plugin DB access |
| Grok vision pipeline | `plugins/grok/vision/` | analyzer, cache, quota, schemas, video_schemas |
| Grok config | `plugins/grok/config/` | `schema.py`, `builder.py`, `validation.py` |
| Grok tests | `plugins/grok/tests/` | Tests across all modules |
| Grok profile defaults | `plugins/grok/profile_defaults.py` | `build_default_profile()` |
| Grok compat | `plugins/grok/compat.py` | `import_sibling_plugin_module()` |
| Grok delivery | `plugins/grok/delivery/` | `send_reply()` — split + send + retry |
| Grok context | `plugins/grok/context/` | `evidence.py` — `AgentToolCall`, `EvidenceBlock`, `ContextBundle` |
| Grok shared | `plugins/grok/shared/` | Conversation history helpers, LLM chain logger, tool metadata |

## GROK PLUGIN DATA FLOW

```
NcatBot Event → GrokPlugin.on_group_message()
  → trigger.prefilter_event()        # cheap gate (enabled, target, prefix/@)
  → _has_reply_segment()?             # quick reply check before DB wait
  → bridge.wait_until_visible()      # read-after-write retry (5s timeout)
  → trigger.final_decision()         # cooldown, reply-to-bot
  → trace_store.insert_trace()
  → profile_json_store.observe_user() + auto-create blank profile
  → AgentRuntime.run()               # multi-turn loop (≤max_steps):
      ├── run_agent_turn()           # call LLM with tools
      ├── tool calls? → execute(registry) → append evidence
      └── no tool calls? → text response done
  → delivery.send_reply()            # split + send
  → conversation_store.upsert_session()
  → trace_store.finish_trace()
```

## JSON PROFILE STORE

File: `<project_root>/data/grok/profiles.json` (configurable via `profile.db_path`)

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
| `MessageStorage` | `image_analyses` | Permanent | Per-user recall, system notices |

Ban/unban events are also written as `media_type="system_notice"` entries in `image_analyses`.

## CONVENTIONS

- **Async everywhere**: All network and database I/O is async. Blocking filesystem work
  should go through `asyncio.to_thread()`.
- **Dataclasses for DTOs**: Use `@dataclass` for config and transfer objects, not Pydantic.
- **Config layout**: Root `config.yaml` is NcatBot runtime (adapters). Plugin configs in
  `plugins/*/config.yaml`. Plugin `config.yaml` files are gitignored — use `config.example.yaml`.
- **Image detection**: 3-layer cascade: URL extension → Content-Type → magic bytes → `.jpg`.
- **Deduplication**: Use content MD5, not `file_unique`.
- **Plugin entry**: `manifest.toml` → `plugin.py` → `entry_class`.
- **Versioning**: Keep `pyproject.toml`, plugin manifest version, plugin class version,
  and `CHANGELOG.md` aligned.
- **Build backend**: setuptools via `pyproject.toml`. Runtime: `uv run ncatbot run`.
- **Business logic separation**: `plugin.py` is thin event routing only. Business logic
  lives in `app/`, `tools/`, `trigger/`, `prompt_synthesizer/` modules.
- **Cross-plugin access**: `grok` reads `qq_recorder` DB via `RecorderBridge` (dynamic
  import via `compat.py`). Never import recorder models directly.
- **Third-party code**: Do not edit `napcat/`.
- **Docs scope**: `docs/` is vendored NcatBot documentation, not project-specific.
- **PYRIGHT_ZERO**: All `# type: ignore` in runtime code is banned. Only test mocks may
  use `type: ignore[assignment]` with justification.

## ANTI-PATTERNS

- **NEVER** suppress type errors with `# type: ignore` in new code (except test mocks).
- **NEVER** use empty `except` blocks.
- **NEVER** save all images as `.jpg`.
- **NEVER** block the event loop with sync I/O in the message path.
- **NEVER** modify NcatBot event objects in-place; convert with `event_to_dict()` first.
- **NEVER** rely on `file_unique` for image deduplication.
- **NEVER** rely on `is_sticker` / `stickerId` alone; use `segment_data["sub_type"]`.
- **NEVER** add business logic in `plugin.py` — use `app/`, `tools/`, or `trigger/` modules.
- **NEVER** call `get_forward_msg` for forward content — read from recorder DB or use
  inline fallbacks instead.
- **NEVER** use `import` inside functions at call time (except `lazy_import` in compat.py).

## COMMANDS

```bash
uv sync
uv run ncatbot run
uv run ruff check plugins/
uv run ruff format plugins/ --check
uv run pyright plugins/
uv run pytest plugins/grok/tests/ plugins/qq_recorder/tests/
python scripts/export_db.py summary
python scripts/backup_tool.py list --dir data/qq_recorder/data/backups
```

## NOTES

- `data/qq_recorder/` is the recorder plugin runtime workspace. Paths in recorder config
  are relative to that workspace.
- `data/grok/profiles.json` is the grok profile store, at the project root level.
  Config: `profile.db_path: "../../data/grok/profiles.json"` relative to `plugins/grok/`.
- `grok` plugin name in config is `grok` (dir), `GrokPlugin` (class), `"grok"` (manifest).
- Profile data is managed in JSON (`data/grok/profiles.json`), not in `config.yaml`.
- Thinking mode: set `thinking_enabled: true` + `thinking_effort: max` in model config.
  Passed as `extra_body={"thinking": {"type": "enabled"}}` + `reasoning_effort`.
- Forward message API (`get_forward_msg`) is unreliable for inner/nested forwards.
  Fallback order: API → CQ embed → inline `node` segments. The `extract_forward` tool
  in grok does parallel DB lookups via `get_message(forward_id)` before API fallback.
- Plugin configs (`plugins/*/config.yaml`) are gitignored. Copy from `config.example.yaml`.
- Root `config.yaml` may contain secrets; do not commit credentials.
