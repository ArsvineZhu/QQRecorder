# QQContextBot Reply Plugin

`qq_grok_reply` is the guarded AI reply plugin for QQContextBot. It reads context
from the recorder database, decides whether a message should trigger a reply, builds
topic-aware or recent-message context, calls the configured model provider, and sends
the response back through NcatBot. Python 3.12+, async throughout.

This plugin uses a **two-round** approach:
1. First round: lightweight context + `request_more_context` tool
2. Second round: expanded context (no more tools), only final answer

## DATA FLOW

```
NcatBot Event → plugin._handle() → app.flow.handle_event()
  ├─ trigger.prefilter_event() → cheap trigger gate
  ├─ RecorderBridge.wait_until_visible() → read recorder row after write
  ├─ trigger.final_decision() → cooldown / reply-to-bot / prefix / @ logic
  ├─ context.build_context() → topic_ai or recent context assembly
  ├─ llm.generate_reply() → first pass (tool allowed) or second pass (final answer)
  ├─ delivery.send_reply() → group/private send helpers
  └─ infra.TraceStore → decision + context + result tracking
```

## STRUCTURE

```
plugins/qq_grok_reply/
├── plugin.py              # QQGrokReplyPlugin
├── manifest.toml
├── config.py              # Config assembly + target checks
├── config_schema.py       # Dataclass schemas
├── config_validation.py   # Validation rules
├── compat.py              # Cross-plugin import helper
├── models.py              # ReplyTrace model
├── app/
│   └── flow.py            # Main per-message orchestration
├── context/
│   ├── builder.py         # Recorder DB → prompt context
│   ├── render.py          # Text render/trim helpers
│   ├── types.py           # BuiltContext, TopicContextError
│   ├── legacy_forward.py  # Legacy forward hydration
│   └── message_renderer.py # Structured message textification
├── llm/
│   ├── client.py          # AI provider integration (single tool: request_more_context)
│   ├── prompt.py          # Prompt assembly
│   └── topic_analyzer.py  # Topic summarization
├── infra/
│   ├── recorder_bridge.py # Cross-plugin DB bridge
│   └── trace_store.py     # Trace persistence
├── delivery/
│   ├── sender.py          # Reply sending helpers
│   └── text_splitter.py   # Long-text chunking
├── trigger/
│   └── rules.py           # Prefilter, cooldown, final decision
├── shared/
│   └── utils.py           # Shared utilities
├── vision/
│   ├── analyzer.py        # DashScope image analysis
│   ├── cache.py           # Vision cache (vision_cache table)
│   ├── client.py          # DashScope client creation
│   ├── quota.py           # Daily quota tracker
│   ├── router.py          # Model selection/escalation
│   ├── schemas.py         # VisualAnalysis dataclass
│   ├── video_analyzer.py  # Video analysis
│   ├── video_schemas.py   # VideoAnalysis dataclass
│   └── prompts.py         # Vision system prompts
├── config.yaml
├── config.example.yaml
└── tests/
    ├── test_plugin_flow.py
    ├── test_prompt.py
    ├── test_model_client.py
    ├── test_context_builder.py
    ├── test_message_renderer.py
    ├── test_recorder_bridge.py
    ├── test_sender.py
    ├── test_text_splitter.py
    ├── test_topic_analyzer.py
    ├── test_trace_store.py
    ├── test_config_and_trigger.py
    ├── test_vision.py
    ├── test_compat.py
    └── test_plugin_smoke.py
```

## KEY DIFFERENCES FROM `grok` PLUGIN

| Aspect | `qq_grok_reply` | `grok` |
|--------|----------------|--------|
| Rounds | Fixed two-round | Multi-turn loop (up to max_steps) |
| Tools | Single `request_more_context` | 9 tools (track_reply, load_context, read_picture, profile CRUD, etc.) |
| Profile | None | JSON file store, auto-create |
| Thinking | Not supported | `extra_body` + `reasoning_effort` |
| Vision | Same vision pipeline | Same vision pipeline |
| Ban detection | No | `handle_group_ban()` → profile + recorder notice |

## CONVENTIONS

- **Plugin entry**: `QQGrokReplyPlugin`.
- **Recorder dependency**: `recorder_db` must be absolute path to live recorder SQLite.
- **Trigger gating**: Cheap prefilter first, wait for recorder row, then final decision.
- **Cooldowns**: Separate windows for group chat, group user, private user.
- **Cross-plugin imports**: Use `compat.import_sibling_plugin_module()`.
- **Traceability**: Use `TraceStore` when enabled.

## GOTCHAS

- `wait_until_visible()` exists because recorder row may not be immediately available.
- `allow_reply_to_bot` uses trace store to avoid duplicate reactions.
- `prefilter_event()` and `final_decision()` are separate: cheap gate vs full policy.
- `build_context()` can return topic-aware or recent-message fallback.
- `qq_recorder` is a sibling plugin; use bridge/compat helpers to access it.
