# Changelog

All notable changes to QQContextBot are documented here.

## Unreleased

- **`qq_grok_reply` removed**: Plugin fully deleted. `backfill.py` fallback import updated
  to prefer `grok` schemas with graceful ImportError fallback.
- **Forward parser 3-tier fallback**: `get_forward_msg` → CQ embedded JSON content
  (`parse_forward_embed`) → inline `type: "node"` segments in event message array
  (`extract_inline_forward_nodes`). Handles new NapCat behavior where `content` is
  `[object Object]` but actual node data is available as a list in `segment.data.content`.
- **Grok `extract_forward` DB-first**: Before calling the failing API, now looks up the
  forward message by `forward_id` directly via `bridge.get_message()`.
- **Orchestrator fast gate**: Messages without a `reply` segment skip the 5-second
  `wait_until_visible()` loop entirely when prefilter rejects.
- **Line-safe logging**: `_LineSafeFormatter` wraps all root handler formatters at boot,
  escaping `\n` in every log output. NapCat adapter lines are now single-line.
- **Log preview escaping**: `model_adapter.py` text-response preview uses
  `text[:120].replace("\n", "\\n")`. `events.py` `format_stored_log` escapes newlines
  after truncation.
- **Profile data relocation**: Profiles moved from `data/qq_agent_reply/data/profiles.json`
  to `data/grok/profiles.json`. Config `profile.db_path` updated to
  `../../data/grok/profiles.json`.
- **Pyright clean**: All pyright errors in the project fixed — test mock `type: ignore`,
  `prompt_synthesizer` test assertions, backfill import fallback.
- **130 tests passing**: All previous test regressions (prompt template assertions,
  backfill module) resolved.
- **`CLAUDE.md` fully rewritten**: Removed all references to `qq_grok_reply`, updated tool
  count, structure, profile path, data flow, conventions, and anti-patterns.

## 1.5.1 - 2026-05-22

- Backup tooling for full and incremental SQLite/image archives.
- Message processing throughput improvements.
- SQLite lock retry handling in the recorder write path.
- Image download fast-path reuse and stream-checked size limits.

## 1.5.0

- Sticker detection pipeline with metadata, text, and heuristic layers.
- App-share parsing and persistence for QQ JSON share cards.
- Recorder stats updated to include sticker counts.
