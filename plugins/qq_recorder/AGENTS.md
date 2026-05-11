# QQRecorder Plugin

NcatBot plugin that silently records QQ group/private messages to SQLite with image download and forward parsing.

## DATA FLOW

```
NcatBot Event → events.event_to_dict() → processors.MessageProcessor.process_message()
  ├─ config.is_chat_monitored() → filter
  ├─ message_parser.parse_message(raw_message) → ParsedMessage (images, replies, forwards, ats)
  │   └─ extract_images() → sticker_detector.combined_detection() → ImageInfo(is_sticker, sticker_confidence)
  ├─ forward_parser: api.qq.get_forward_msg() → parse_forward_response() → flatten_forward_nodes()
  ├─ storage.save_message() → Message + related records in SQLite
  └─ image_handler.process_images() → download → detect extension → save → update DB
```

## MODULES

| File | Role | Key Exports |
|------|------|-------------|
| `plugin.py` | Plugin class: lifecycle, event handler registration (thin orchestrator) | `QQRecorderPlugin` |
| `events.py` | Pure utilities: event conversion, command detection, log formatting | `event_to_dict()`, `is_command()`, `format_stored_log()` |
| `commands.py` | Command handling: stats/recent/search subcommands | `CommandHandler`, `get_chat_info()`, `format_message_brief()` |
| `processors.py` | Message processing pipeline: message/forward/image handling | `MessageProcessor` |
| `config.py` | Config models + validation + monitoring check | `RecorderSettings`, `is_chat_monitored()` |
| `models.py` | SQLAlchemy ORM schema | `Message`, `Image`, `ForwardMessage`, `Reply`, `AtMention` |
| `storage.py` | Async DB operations | `MessageStorage` |
| `message_parser.py` | Segment parsing (text/image/at/reply/forward) | `parse_message()`, `ParsedMessage`, `ImageInfo` |
| `image_handler.py` | Download, format detect, save | `process_images()`, `detect_extension()` |
| `forward_parser.py` | Recursive forward node parsing | `parse_forward_response()`, `ForwardNode` |
| `sticker_detector.py` | 3-layer sticker detection cascade | `combined_detection()`, `detect_by_metadata()`, `detect_by_text()`, `detect_by_heuristics()` |

## CONVENTIONS (PLUGIN-SPECIFIC)

- **Plugin entry**: NcatBot loads via `manifest.toml` → `main = "plugin.py"` → `entry_class = "QQRecorderPlugin"`. No separate `main.py` re-export.
- **Command prefixes**: `("recorder", "/recorder", "r", "/r")` — registered via `@registrar.qq.on_group_command()`.
- **Extension detection order**: URL ext → Content-Type → magic bytes → fallback `.jpg`. Never skip a layer.
- **MD5 filenames**: Images saved as `<md5hash>.<ext>` for auto-dedup. Hash is of binary content, not URL.
- **Forward depth**: Configurable via `forward.max_depth` (default 10, max 50). Prevents infinite recursion.
- **Per-message error isolation**: `MessageProcessor.process_message()` wraps everything in try/except — one bad message never kills the plugin.
- **Sticker detection order**: sub_type metadata (primary, 0.95) → CQ码 text pattern (0.95) → heuristic format+size (0.7-0.85). Combined confidence ≥ 0.7 marks as sticker.
- **Sticker detection invoked in parse**: `extract_images()` in `message_parser.py` calls `combined_detection()` — no separate step in the pipeline.

## ANTI-PATTERNS (THIS PLUGIN)

- **NEVER** add sync I/O in the message processing path — use `asyncio.to_thread()` for any blocking call
- **NEVER** hardcode `.jpg` as image extension — always use `detect_extension()` cascade
- **NEVER** access `self.api` before `on_load()` completes — API is only available after plugin init
- **NEVER** modify `event` objects in-place — convert to dict first via `event_to_dict()`
- **NEVER** rely on `is_sticker` / `stickerId` fields in QQ segment_data — use `sub_type` instead (0=image, 1=animated sticker, 7=shop sticker, 13=emoji sticker)
- **NEVER** pass `raw_message` as the sole data source for sticker detection — always also check `segment_data` dict for `sub_type` field

## GOTCHAS

- `ImageInfo.file_unique` is often `"0"` from QQ — don't rely on it for dedup. Use `file_url` for querying and MD5 hash for dedup.
- `event_to_dict()` manually extracts fields because NcatBot event objects don't serialize cleanly.
- Storage paths in config are relative to `self.workspace` (plugin's data dir), not project root.
- `ForwardMessage` is self-referential (`parent_forward_id` FK to self) — tree is stored as adjacency list.
- Forward IDs from parsed messages may be empty/whitespace — always filter before calling API.
- `segment_data.get("sub_type", 0)` is the primary sticker detection signal: 0=普通图片, 1=动画表情, 7=QQ商城贴纸, 13=emoji小表情. Some stickers may have sub_type=0 (false negative) — the text-based and heuristic layers cover these edge cases.
- `sub_type=1` in CQ码 raw_message (e.g., `[CQ:image,sub_type=1,...]`) can also be detected via regex on raw_message string — this catches cases where segment_data parsing loses the field.
- `is_sticker` defaults to `False` (0) for all records — only explicitly set to `True` when confidence ≥ 0.7. Backfilled records have confidence 0.95 when detected via metadata/text, 0.5-0.85 when detected via heuristics.
- The `face` segment type is a separate QQ emoji system, NOT related to image-type stickers — do not conflate `face` segments with `image` sticker detection.
