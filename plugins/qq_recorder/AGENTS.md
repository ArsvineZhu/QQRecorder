# QQContextBot Recorder Plugin

NcatBot recorder plugin inside QQContextBot. It silently records QQ group/private
messages to SQLite with image download, forward parsing (3-tier fallback), sticker
detection, app share parsing, video processing, vision analysis persistence, and
scheduled backup/restore. Python 3.12+, async throughout.

Newlines in all log output (including third-party loggers like NapCatAdapter) are
escaped at the formatter level via ``_LineSafeFormatter`` installed at boot.

## DATA FLOW

```
NcatBot Event -> events.event_to_dict() -> processors.MessageProcessor.process_message()
  ├─ config.is_chat_monitored() -> filter
  ├─ processing.max_inflight semaphore -> backpressure
  ├─ message_parser.parse_message(event.message, raw_message) -> ParsedMessage
  │   ├─ extract_images() -> sticker_detector.combined_detection() -> ImageInfo
  │   └─ extract_app_shares() -> HTML unescape -> JSON parse -> AppShareInfo
  ├─ extract_forward_embeds() + extract_inline_forward_nodes() from segments
  ├─ _process_forwards(forward_ids, embeds, inline_nodes)
  │   └─ 3-tier fallback:
  │       1. get_forward_msg API
  │       2. parse_forward_embed() — URL+HTML decoded JSON from CQ content
  │       3. parse_forward_nodes() — inline "node" segments in event.message
  ├─ storage.save_message() -> Message + related records in SQLite
  └─ image_handler.process_images() -> URL fast-path reuse OR stream download -> save
```

## STRUCTURE

```
plugins/qq_recorder/
├── plugin.py              # Plugin entry: QQRecorderPlugin, _install_line_safe_logging()
├── manifest.toml
├── events.py              # Event conversion + format_stored_log() + command detection
├── commands.py            # stats/recent/search
├── processors.py          # Message pipeline orchestrator, 3-tier forward fallback
├── config.py              # RecorderSettings
├── models.py              # SQLAlchemy ORM tables (10 tables)
├── storage.py             # Async DB operations (includes save_image_analysis)
├── message_parser.py      # Segment parsing -> ParsedMessage DTOs, extract_inline_forward_nodes
├── forward_parser.py      # parse_forward_response, parse_forward_embed, parse_forward_nodes
├── image_handler.py       # Download + format detection + save
├── video_handler.py       # Video download + metadata extraction
├── sticker_detector.py    # 3-layer sticker detection cascade
├── text_utils.py          # Control char escape/unescape
├── backup.py              # Full/incremental backup and restore
├── outbound_recorder.py   # Record bot's own outgoing messages
├── AGENTS.md
└── tests/
    ├── test_backup.py
    ├── test_forward_pipeline.py
    ├── test_reliability_pipeline.py
    ├── test_sticker_detection.py
    ├── test_video_and_outbound.py
    └── __init__.py
```

## KEY TABLES

| Table | Class | Purpose |
|-------|-------|---------|
| `messages` | `Message` | Core message entity |
| `message_segments` | `MessageSegment` | Individual segments (text, image, at, etc.) |
| `images` | `Image` | Image metadata + download status + sticker detection |
| `videos` | `Video` | Video metadata + download status |
| `replies` | `Reply` | Reply-to relationships |
| `forward_messages` | `ForwardMessage` | Self-referencing adjacency list for merged forwards |
| `at_mentions` | `AtMention` | @-mention targets |
| `app_shares` | `AppShare` | Structured QQ share card data |
| `image_analyses` | `ImageAnalysis` | Permanent LLM vision analysis results + system notices |
| `monitored_chats` | `MonitoredChat` | Runtime chat monitoring list |

## IMPORTANT NOTES

- `ImageAnalysis` is written by `grok` plugin after vision analysis, and also by
  `ban_handler.py` for mute/unmute system notices (`media_type="system_notice"`).
- `forward_parser.extract_text_from_content()` covers all segment types with
  descriptive labels like `[图片]`, not just `type=="text"`.
- Forward parsing has 3 fallbacks: API → CQ embed → inline nodes (see DATA FLOW).
- `events.py` `format_stored_log()` escapes newlines in `raw` after truncation.
- `plugin.py` `_install_line_safe_logging()` wraps root handlers with
  `_LineSafeFormatter` so *all* log output (even from NapCatAdapter) is single-line.
- `message_parser.extract_inline_forward_nodes()` handles NapCat's new behavior where
  `data.content` is a decoded Python list of node dicts (instead of a string).
- `backfill.py` imports from `grok.vision.schemas` first, falls back to deleted
  `qq_grok_reply` for backward compatibility.

## CONVENTIONS

- **Plugin entry**: `manifest.toml` → `plugin.py` → `entry_class = "QQRecorderPlugin"`.
- **Command prefixes**: `("recorder", "/recorder", "r", "/r")`.
- **Extension detection order**: URL ext → Content-Type → magic bytes → fallback `.jpg`.
- **MD5 filenames**: Images saved as `<md5hash>.<ext>` for dedup.
- **URL fast-path reuse**: Same `file_url` + existing local file skips re-download.
- **Forward depth**: Configurable via `forward.max_depth`. Nodes beyond depth are pruned.
- **Lock retry**: Exponential backoff on `database is locked`.
- **Sticker detection order**: metadata → text → heuristic. Confidence ≥ 0.7 marks sticker.
- **Event immutability**: Convert to dict first; do not mutate event objects in-place.
