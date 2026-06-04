# Changelog

All notable changes to QQContextBot are documented here.

## Unreleased

- **New plugin `grok`**: Full-featured multi-turn Agent reply plugin with 9 tools,
  JSON profile store, thinking mode, ban detection, and vision result persistence.
  Renamed from `qq_agent_reply`.
- **`ImageAnalysis` table** in recorder DB: permanent storage for image/video AI
  interpretation results, also used for `system_notice` records (ban/unban events).
- **Forward parser upgrade**: Non-text segments (image, video, face, at, reply, etc.)
  now produce descriptive labels `[图片]`, `[视频]`, `[@xxx]` etc. in `content_summary`.
- **Config refactored to `config/` package**: Flat `config.py`/`config_schema.py`/
  `config_validation.py` → `config/__init__.py`/`schema.py`/`builder.py`/`validation.py`.
- **User profile moved to JSON file**: Profiles stored in `data/profiles.json`,
  removed `profile.users` from YAML config + old `AgentProfileStore` SQLite.
- **`ProfileUserConfig` removed** from `config/schema.py`.
- **Profile tools expanded**: `create_profile`, `update_profile`, `delete_profile` added.
  `load_profile` auto-creates blank profiles for new users on first contact.
- **`handle_group_ban()`** in `app/ban_handler.py`: bot mute/unmute events → profile mute
  state + recorder `image_analyses` system notice.
- **Thinking mode**: `thinking_enabled` + `thinking_effort` in model config. Passes
  `extra_body={"thinking": {"type": "enabled"}}` + `reasoning_effort`.
- **Runtime logging**: Added structured `logger.info` to `trigger/rules.py`,
  `app/orchestrator.py`, `app/runtime.py`, `agent/model_adapter.py`.
- **`extract_forward`** now reads from recorder DB only (live `get_forward_msg` API is
  unreliable for expired messages).
- **`read_picture` fix**: Fresh-reloads the message from DB before reading image bytes
  (fixes stale `local_path` issue). Also attaches `message_text` in the response.
- **`MessageStorage.save_image_analysis()`** and `get_image_analysis()` added to recorder
  storage layer.
- **`RecorderBridge`** exposes `save_analysis()` / `get_analysis()` helpers.
- **Pyright clean**: All `# type: ignore` removed, zero errors project-wide.
- **`CLAUDE.md`** rewritten to match actual codebase.

## 1.5.1 - 2026-05-22

- Backup tooling for full and incremental SQLite/image archives.
- Message processing throughput improvements.
- SQLite lock retry handling in the recorder write path.
- Image download fast-path reuse and stream-checked size limits.

## 1.5.0

- Sticker detection pipeline with metadata, text, and heuristic layers.
- App-share parsing and persistence for QQ JSON share cards.
- Recorder stats updated to include sticker counts.
