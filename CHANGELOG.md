# Changelog

All notable changes to QQContextBot are documented here.

## Unreleased

- Rebranded the project entry point to `QQContextBot` while keeping package names
  stable for compatibility.
- Added plugin-level `AGENTS.md` files for both `qq_recorder` and `qq_grok_reply`.
- Added usage documentation for tool scripts under `scripts/README.md`.
- Retired the one-click version synchronization script in favor of manual version and
  changelog updates.

## 1.5.1 - 2026-05-22

- Backup tooling for full and incremental SQLite/image archives.
- Message processing throughput improvements, including in-flight backpressure and
  image download concurrency caps.
- SQLite lock retry handling in the recorder write path.
- Image download fast-path reuse and stream-checked size limits.

## 1.5.0

- Sticker detection pipeline with metadata, text, and heuristic layers.
- App-share parsing and persistence for QQ JSON share cards.
- Recorder stats updated to include sticker counts.
