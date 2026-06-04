# QQContextBot Reply Plugin

`qq_grok_reply` is the guarded AI reply plugin for QQContextBot. It reads context
from the recorder database, decides whether a message should trigger a reply, builds
topic-aware or recent-message context, calls the configured model provider, and sends
the response back through NcatBot. Python 3.12+, async throughout.

## DATA FLOW

```
NcatBot Event -> plugin._handle() -> app.flow.handle_event()
  ├─ trigger.prefilter_event() -> cheap trigger gate
  ├─ RecorderBridge.wait_until_visible() -> read recorder row after write
  ├─ trigger.final_decision() -> cooldown / reply-to-bot / prefix / @ logic
  ├─ context.build_context() -> topic_ai or recent context assembly
  ├─ llm.generate_reply() -> LLM / adapter call
  ├─ delivery.send_reply() -> group/private send helpers
  └─ infra.TraceStore -> decision + context + result tracking
```

## STRUCTURE

```
plugins/qq_grok_reply/
├── plugin.py              # QQGrokReplyPlugin entry, lifecycle, thin event delegation
├── manifest.toml          # NcatBot plugin descriptor
├── config.py              # config assembly + target checks
├── config_schema.py       # dataclass schemas for reply settings
├── config_validation.py   # configuration validation rules
├── compat.py              # compatibility imports for recorder models/storage
├── models.py              # reply-plugin DB models
├── app/
│   └── flow.py            # main per-message orchestration
├── context/
│   ├── builder.py         # recorder data -> prompt context
│   ├── render.py          # render/trim helpers for context text
│   ├── types.py           # BuiltContext and error types
│   ├── legacy_forward.py  # legacy forward hydration helpers
│   └── message_renderer.py # structured message textification
├── llm/
│   ├── client.py          # AI provider integration
│   ├── prompt.py          # prompt assembly
│   └── topic_analyzer.py  # topic summarisation and validation
├── infra/
│   ├── recorder_bridge.py # cross-plugin DB bridge to qq_recorder models
│   └── trace_store.py     # decision / error / send trace persistence
├── delivery/
│   ├── sender.py          # reply sending helpers
│   └── text_splitter.py   # long-text chunking helpers
├── trigger/
│   └── rules.py           # prefilter, cooldown, final decision
├── shared/
│   └── utils.py           # shared utility helpers
└── tests/
    ├── test_*.py         # config, context, model, sender, bridge, prompt, smoke, flow
    └── __init__.py
```

## MODULES

| File | Role | Key Exports |
|------|------|-------------|
| `plugin.py` | Plugin lifecycle and thin event delegation | `QQGrokReplyPlugin` |
| `app/flow.py` | Main reply orchestration for one event | `handle_event()` |
| `config.py` | Build settings and check chat targeting | `build_config()`, `is_chat_targeted()`, `RECORDER_COMMAND_PREFIXES` |
| `config_schema.py` | Dataclass schemas for nested config | `ReplyPluginSettings`, `TriggerConfig`, `ContextConfig`, `ModelConfig`, ... |
| `config_validation.py` | Validate config invariants and ranges | `validate_config()` |
| `trigger/rules.py` | Prefilter, cooldown tracking, and final trigger decisions | `CooldownTracker`, `prefilter_event()`, `final_decision()` |
| `context/builder.py` | Build prompt context from recorder DB rows and runtime metadata | `build_context()`, `TopicContextError` |
| `context/render.py` | Render, trim, and select context blocks | `render_message()`, `render_line()`, `trim()`, `unique()`, ... |
| `context/types.py` | Context DTOs and related error types | `BuiltContext`, `TopicContextError` |
| `context/legacy_forward.py` | Hydrate legacy forward records before rendering | `hydrate_legacy_forward_message()`, `hydrate_legacy_forward_messages()` |
| `context/message_renderer.py` | Render structured segments into readable text | `render_message_text()`, `render_forward_tree()` |
| `infra/recorder_bridge.py` | Read `qq_recorder` data through imported recorder models/storage | `RecorderBridge` |
| `llm/topic_analyzer.py` | Analyze topic candidates and validate results | `TopicAnalysis`, `analyze_topic()`, `validate_topic_analysis()` |
| `llm/prompt.py` | Assemble prompt payloads for the model provider | prompt builders/helpers |
| `llm/client.py` | Provider-specific model call and response parsing | `generate_reply()`, `ReplyModelError` |
| `delivery/sender.py` | Send reply segments through NcatBot | `send_reply()`, `SendOutcome` |
| `infra/trace_store.py` | Persist trigger decisions, prompt summaries, and send results | `TraceStore` |
| `delivery/text_splitter.py` | Split long responses into safe parts | splitter helpers |
| `shared/utils.py` | Shared utility helpers for payload formatting and awaitable handling | `json_list()`, `json_payload()`, `resolve_awaitable()`, ... |
| `compat.py` | Import sibling `qq_recorder` modules safely | import helpers for bridge compatibility |

## CONVENTIONS

- **Plugin entry**: NcatBot loads via `manifest.toml` -> `plugin.py` -> `entry_class = "QQGrokReplyPlugin"`.
- **Recorder dependency**: `recorder_db` must be an absolute path and must point at the live `qq_recorder` SQLite file.
- **Trigger gating**: The plugin first runs a cheap prefilter, then waits for the recorder row to appear, then applies final decision logic.
- **Cooldowns**: Separate cooldown windows apply to group chat, group user, and private user traffic.
- **Reply-to-bot support**: Optional reply-to-bot handling is gated by config and trace bookkeeping.
- **Context modes**: Topic-aware context is preferred when the analyzer is enabled and the runtime API is available; otherwise recent-message fallback is used.
- **Cross-plugin imports**: Use `compat.import_sibling_plugin_module()` for recorder-side models/storage instead of hard-coding package import paths.
- **Traceability**: Trigger decisions, context summary, model summaries, and send outcomes should be recorded through `TraceStore` when enabled.
- **Logging**: Runtime logs are intentionally structured and compact; keep payloads JSON-like and bounded by the configured character limit.
- **Async everywhere**: Network and database work must stay async. Use `resolve_awaitable()` when the underlying API may be sync or async.

## ANTI-PATTERNS

- **NEVER** pass a relative `recorder_db` path.
- **NEVER** call the model if the trigger gate rejects the event.
- **NEVER** bypass `RecorderBridge` to query recorder storage directly inside the plugin.
- **NEVER** bypass `TraceStore` when tracing is enabled.
- **NEVER** treat the recorder command prefix as a reply trigger when `ignore_recorder_command` is set.
- **NEVER** assume the topic analyzer is always available; keep the recent-context fallback working.
- **NEVER** access `self.api` before `on_load()` has completed.
- **NEVER** add sync I/O to the reply path.

## GOTCHAS

- `RecorderBridge.wait_until_visible()` exists because the recorder row may not be visible immediately after the event arrives.
- `allow_reply_to_bot` can intentionally create replies on existing bot content; the trace store is used to avoid duplicate reactions.
- `prefilter_event()` and `final_decision()` are separate on purpose: one is a cheap early gate, the other is the full policy decision.
- `build_context()` can return topic-aware or recent-message contexts depending on analyzer availability and config.
- `topic_analyzer` may fall back to recent context when configured to do so; this is not an error unless fallback is disabled.
- `qq_recorder` is a sibling plugin, not a module in this package. Use the bridge and compat helpers when crossing that boundary.
- The plugin stores runtime traces in the same recorder database, so schema compatibility matters when the recorder plugin changes.
- `qq_grok_reply` is independent from the recorder plugin lifecycle, but it depends on the recorder database being present and current.
