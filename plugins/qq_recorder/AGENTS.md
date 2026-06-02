# QQContextBot Recorder Plugin

NcatBot recorder plugin inside QQContextBot. It silently records QQ group/private
messages to SQLite with image download, forward parsing, sticker detection, app share
parsing, and scheduled backup/restore. 14 source files, 4 test modules. Python 3.12+,
async throughout.

## DATA FLOW

```
NcatBot Event -> events.event_to_dict() -> processors.MessageProcessor.process_message()
  ├─ config.is_chat_monitored() -> filter
  ├─ processing.max_inflight semaphore -> backpressure
  ├─ message_parser.parse_message(raw_message) -> ParsedMessage (images, replies, forwards, ats, app_shares)
  │   ├─ extract_images() -> sticker_detector.combined_detection() -> ImageInfo(is_sticker, sticker_confidence)
  │   └─ extract_app_shares() -> HTML unescape -> JSON parse -> AppShareInfo
  ├─ forward_parser.parse_forward_response() -> flattened forward tree
  ├─ storage.save_message() -> Message + related records in SQLite
  └─ image_handler.process_images() -> URL fast-path reuse OR stream download -> detect extension -> save -> update DB
```

## STRUCTURE

```
plugins/qq_recorder/
├── plugin.py              # Plugin entry: QQRecorderPlugin
├── manifest.toml          # NcatBot plugin descriptor
├── events.py              # Event conversion + command detection
├── commands.py            # stats/recent/search command handler
├── processors.py          # Message pipeline orchestrator
├── config.py              # RecorderSettings + monitoring filter
├── models.py              # SQLAlchemy ORM tables
├── storage.py             # Async DB operations
├── message_parser.py      # Segment parsing -> ParsedMessage DTOs
├── image_handler.py       # Download + format detection + save
├── backup.py              # Full/incremental backup and restore chains
├── forward_parser.py      # Recursive forward node parsing
├── sticker_detector.py    # 3-layer sticker detection cascade
├── text_utils.py          # Control char escape/unescape
└── tests/
    ├── test_backup.py
    ├── test_reliability_pipeline.py
    └── test_sticker_detection.py
```

## MODULES

| File | Role | Key Exports |
|------|------|-------------|
| `plugin.py` | Plugin class, lifecycle, and event handler registration | `QQRecorderPlugin` |
| `events.py` | Pure utilities: event conversion, command detection, log formatting | `event_to_dict()`, `is_command()`, `format_stored_log()` |
| `commands.py` | Command handling: stats/recent/search | `CommandHandler` |
| `processors.py` | Message pipeline: message/forward/image/app-share handling | `MessageProcessor` |
| `config.py` | Config models + validation + monitoring checks | `RecorderSettings`, `is_chat_monitored()` |
| `models.py` | SQLAlchemy ORM schema | `Message`, `Image`, `ForwardMessage`, `Reply`, `AtMention`, `AppShare` |
| `storage.py` | Async DB operations | `MessageStorage` |
| `message_parser.py` | Segment parsing | `parse_message()`, `ParsedMessage`, `ImageInfo`, `AppShareInfo`, `extract_app_shares()` |
| `image_handler.py` | Download, format detect, save | `process_images()`, `detect_extension()` |
| `forward_parser.py` | Recursive forward node parsing | `parse_forward_response()`, `ForwardNode` |
| `sticker_detector.py` | Sticker detection cascade | `combined_detection()`, `detect_by_metadata()`, `detect_by_text()`, `detect_by_heuristics()` |
| `backup.py` | Backup and restore orchestration | `BackupManager` |
| `text_utils.py` | Control char escaping for DB storage | `escape_text()`, `unescape_text()` |

## CONVENTIONS

- **Plugin entry**: NcatBot loads via `manifest.toml` -> `plugin.py` -> `entry_class = "QQRecorderPlugin"`.
- **Command prefixes**: `("recorder", "/recorder", "r", "/r")` for group and private commands.
- **Extension detection order**: URL ext -> Content-Type -> magic bytes -> fallback `.jpg`.
- **MD5 filenames**: Images are saved as `<md5hash>.<ext>` for auto-dedup.
- **URL fast-path reuse**: Same `file_url` + existing local file skips re-download.
- **Forward depth**: Configurable via `forward.max_depth`.
- **Backpressure**: `processing.max_inflight` caps in-flight message processing.
- **Image download concurrency**: `processing.image_download_concurrency` caps concurrent downloads.
- **SQLite lock retry**: `storage.lock_retry` uses exponential backoff on `database is locked`.
- **Per-message error isolation**: One bad message should not break the plugin.
- **Sticker detection order**: metadata -> text -> heuristic. Confidence >= 0.7 marks a sticker.
- **Event immutability**: Convert to dict first; do not mutate event objects in-place.
- **JSON segment types**: App shares are parsed from JSON segments and stored both raw and structured.
- **Version alignment**: Keep `plugin.py` and `manifest.toml` in sync, and record
  version changes in `CHANGELOG.md`.

## ANTI-PATTERNS

- **NEVER** add sync I/O in the message processing path.
- **NEVER** hardcode `.jpg` as the image extension.
- **NEVER** access `self.api` before `on_load()` completes.
- **NEVER** modify event objects in-place.
- **NEVER** rely on `is_sticker` / `stickerId` alone in QQ segment data.
- **NEVER** pass `raw_message` as the only signal for sticker detection.
- **NEVER** add new `# pyright: ignore[...]` suppressions in this plugin.
- **NEVER** use `file_unique` for deduplication.

## GOTCHAS

- `ImageInfo.file_unique` is often `"0"` from QQ. Use `file_url` for querying and MD5 for dedup.
- Default image size limit is 50MB and downloads are stream-checked against the limit.
- `event_to_dict()` exists because NcatBot event objects do not serialize cleanly.
- Storage paths in config are relative to `self.workspace` unless the path is absolute.
- `ForwardMessage` is self-referential and stored as an adjacency list.
- Forward IDs may be empty or whitespace; filter them before calling APIs.
- `segment_data.get("sub_type", 0)` is the primary sticker signal: `0` image, `1` animated sticker, `7` shop sticker, `13` emoji sticker.
- `face` is a different QQ emoji system and is not a sticker signal.
- Plugin version is declared in both `plugin.py` and `manifest.toml`; keep them aligned.
- Test suite entry: `uv run pytest plugins/qq_recorder/tests/`
