# QQRecorder Plugin

NcatBot plugin that silently records QQ group/private messages to SQLite with image download and forward parsing.

## DATA FLOW

```
NcatBot Event → events.event_to_dict() → processors.MessageProcessor.process_message()
  ├─ config.is_chat_monitored() → filter
  ├─ message_parser.parse_message() → ParsedMessage (images, replies, forwards, ats)
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

## CONVENTIONS (PLUGIN-SPECIFIC)

- **Plugin entry**: NcatBot loads via `manifest.toml` → `main = "plugin.py"` → `entry_class = "QQRecorderPlugin"`. No separate `main.py` re-export.
- **Command prefixes**: `("recorder", "/recorder", "r", "/r")` — registered via `@registrar.qq.on_group_command()`.
- **Extension detection order**: URL ext → Content-Type → magic bytes → fallback `.jpg`. Never skip a layer.
- **MD5 filenames**: Images saved as `<md5hash>.<ext>` for auto-dedup. Hash is of binary content, not URL.
- **Forward depth**: Configurable via `forward.max_depth` (default 10, max 50). Prevents infinite recursion.
- **Per-message error isolation**: `MessageProcessor.process_message()` wraps everything in try/except — one bad message never kills the plugin.

## ANTI-PATTERNS (THIS PLUGIN)

- **NEVER** add sync I/O in the message processing path — use `asyncio.to_thread()` for any blocking call
- **NEVER** hardcode `.jpg` as image extension — always use `detect_extension()` cascade
- **NEVER** access `self.api` before `on_load()` completes — API is only available after plugin init
- **NEVER** modify `event` objects in-place — convert to dict first via `event_to_dict()`

## GOTCHAS

- `ImageInfo.file_unique` is often `"0"` from QQ — don't rely on it for dedup. Use `file_url` for querying and MD5 hash for dedup.
- `event_to_dict()` manually extracts fields because NcatBot event objects don't serialize cleanly.
- Storage paths in config are relative to `self.workspace` (plugin's data dir), not project root.
- `ForwardMessage` is self-referential (`parent_forward_id` FK to self) — tree is stored as adjacency list.
- Forward IDs from parsed messages may be empty/whitespace — always filter before calling API.
