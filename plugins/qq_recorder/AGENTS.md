# QQContextBot Recorder Plugin

NcatBot recorder plugin inside QQContextBot. It silently records QQ group/private
messages to SQLite with image download, forward parsing, sticker detection, app share
parsing, vision analysis persistence, and scheduled backup/restore. Python 3.12+,
async throughout.

## DATA FLOW

```
NcatBot Event -> events.event_to_dict() -> processors.MessageProcessor.process_message()
  ├─ config.is_chat_monitored() -> filter
  ├─ processing.max_inflight semaphore -> backpressure
  ├─ message_parser.parse_message(raw_message) -> ParsedMessage
  │   ├─ extract_images() -> sticker_detector.combined_detection() -> ImageInfo
  │   └─ extract_app_shares() -> HTML unescape -> JSON parse -> AppShareInfo
  ├─ forward_parser.parse_forward_response() -> flattened forward tree
  │   (extract_text_from_content now includes [图片] [视频] [表情] etc. for non-text)
  ├─ storage.save_message() -> Message + related records in SQLite
  └─ image_handler.process_images() -> URL fast-path reuse OR stream download -> save
```

## STRUCTURE

```
plugins/qq_recorder/
├── plugin.py              # Plugin entry: QQRecorderPlugin
├── manifest.toml
├── events.py              # Event conversion + command detection
├── commands.py            # stats/recent/search
├── processors.py          # Message pipeline orchestrator
├── config.py              # RecorderSettings
├── models.py              # SQLAlchemy ORM tables (9 tables including ImageAnalysis)
├── storage.py             # Async DB operations (includes save_image_analysis)
├── message_parser.py      # Segment parsing -> ParsedMessage DTOs
├── image_handler.py       # Download + format detection + save
├── backup.py              # Full/incremental backup and restore
├── forward_parser.py      # Recursive forward parsing with segment labels
├── sticker_detector.py    # 3-layer sticker detection cascade
├── text_utils.py          # Control char escape/unescape
├── AGENTS.md
└── tests/
    ├── test_backup.py
    ├── test_reliability_pipeline.py
    ├── test_sticker_detection.py
    └── __init__.py
```

## KEY TABLES

| Table | Class | Purpose |
|-------|-------|---------|
| `messages` | `Message` | Core message entity |
| `message_segments` | `MessageSegment` | Individual segments (text, image, at, etc.) |
| `images` | `Image` | Image metadata + download status + sticker detection |
| `image_analyses` | `ImageAnalysis` | **New** — permanent LLM vision analysis results + system notices |
| `replies` | `Reply` | Reply-to relationships |
| `forward_messages` | `ForwardMessage` | Self-referencing adjacency list for merged forwards |
| `at_mentions` | `AtMention` | @-mention targets |
| `app_shares` | `AppShare` | Structured QQ share card data |
| `monitored_chats` | `MonitoredChat` | Runtime chat monitoring list |

## IMPORTANT NOTES

- `ImageAnalysis` is written by `grok` plugin after vision analysis, and also by
  `ban_handler.py` for mute/unmute system notices (`media_type="system_notice"`).
- `forward_parser.extract_text_from_content()` now covers all segment types with
  descriptive labels like `[图片]`, not just `type=="text"`.
- The `_SEGMENT_LABELS` dict maps segment types to Chinese placeholder text.

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
