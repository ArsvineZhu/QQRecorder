# Grok Plugin — Multi-turn Agent Reply

Multi-turn Agent reply plugin inside QQContextBot. Uses a tool-calling LLM loop
with 9 registered tools, JSON profile store, vision analysis (DashScope), thinking
mode, and ban detection. Python 3.12+, async throughout.

## CORE ARCHITECTURE

```
plugin.py:GrokPlugin (thin event router)
  └─ app/orchestrator.py:handle_event()  (orchestration)
      ├─ prefilter_event()               (cheap gate: enabled, target, prefix/@)
      ├─ _has_reply_segment()?            (quick reply check before DB wait)
      ├─ wait_until_visible()            (read-after-write retry, 5s timeout)
      ├─ final_decision()                (cooldown, reply-to-bot)
      ├─ trace_store.insert_trace()
      ├─ profile store observe + auto-create
      ├─ AgentRuntime.run()              (multi-turn loop, ≤max_steps=12)
      │   └─ run_agent_turn()            (LLM call with tools)
      ├─ send_reply()                    (split + send)
      ├─ conversation_store.upsert_session()
      └─ trace_store.finish_trace()
```

## ORCHESTRATOR (app/orchestrator.py)

- `handle_event()` — main entry, called by `GrokPlugin.on_group_message/on_private_message`.
- **Fast gate**: If `prefilter_reason is None` and `allow_reply_to_bot` is true, checks
  `_has_reply_segment(event)` before entering the 5-second `wait_until_visible()` loop.
  Messages without a `reply` segment skip the wait entirely.
- `track_reply` detection via `trace_store.get_sent_message_ids()`.
- Auto-creates blank profile via `profile_defaults.build_default_profile()`.
- Persists conversation history after successful send via `conversation_store.upsert_session()`.

## PROMISED SYNTHESIZER (prompt_synthesizer/)

Replaced the original `agent/prompt.py` inline rendering. New architecture:

| File | Responsibility |
|------|---------------|
| `system_prompt.py` | `render_system_prompt()` — loads template, resolves `{{placeholder}}` |
| `message_builder.py` | `build_model_messages()` — assembles system + user messages |
| `tool_prompt.py` | `render_tool_access_block()` — dynamic tool description from JSON config |
| `renderers.py` | Evidence block renderers (`@renderer(name)` registry pattern) |
| `user_task.py` | `build_user_content()` — current message, context, profile, roster, budget |
| `context_blocks.py` | Helper blocks for context message rendering |

## REGISTERED TOOLS (tools/)

| Tool | Schema | Handler | Purpose |
|------|--------|---------|---------|
| `track_reply` | `track_reply.json` | `context_tools._track_reply_handler` | Trace reply chain |
| `load_context` | `load_context.json` | `context_tools._load_context_handler` | Load recent chat history |
| `load_message` | `load_message.json` | `context_tools._load_message_handler` | Load one message by ID |
| `extract_forward` | `extract_forward.json` | `context_tools._extract_forward_handler` | Read forward content from DB |
| `read_picture` | `read_picture.json` | `media_tools._read_picture_handler` | Vision analysis for images |
| `read_video` | `read_video.json` | `media_tools._read_video_handler` | Vision analysis for videos |
| `load_profile` | `load_profile.json` | `profile_tools._load_profile_handler` | Read user profile |
| `create_profile` | `create_profile.json` | `profile_tools._create_profile_handler` | Create/overwrite profile |
| `update_profile` | `update_profile.json` | `profile_tools._update_profile_handler` | Partial profile update |
| `delete_profile` | `delete_profile.json` | `profile_tools._delete_profile_handler` | Remove profile |
| `query_chat_history` | `query_chat_history.json` | `history_tools._query_chat_history_handler` | Search recorded messages |
| `load_tool_guide` | `load_tool_guide.json` | `guide_tools._load_tool_guide_handler` | Get tool usage details |
| `terminate` | `terminate.json` | `terminate_tools._terminate_handler` | End current agent turn |

## EXTRACT_FORWARD BEHAVIOR

`extract_forward` has 3 retrieval paths, tried in order:

1. **DB (on same message)**: If the source message already has `forward_messages`
   populated by the recorder, returns immediately.
2. **DB (by forward_id)**: Falls back to `bridge.get_message(forward_id)` — the
   forward's QQ message_id equals the forward_id, so the recorder may have stored it.
3. **API fallback**: Calls `get_forward_msg(forward_id)`. If successful, backfills
   the recorder DB via `backfill_forward_messages()`.

## RECORDER BRIDGE (infra/recorder_bridge.py)

Cross-plugin DB access to `qq_recorder` via dynamic import (`compat.py`).

Key methods:
- `wait_until_visible()` — retry loop for read-after-write consistency
- `get_message()` — full message with all joined relations
- `get_reply_chain()` — follow reply-to links upward
- `get_neighbors()` / `get_after()` / `get_recent_window()` — time-window queries
- `query_chat_history()` — filtered search
- `backfill_forward_messages()` — write API-fetched forward data into DB
- `save_analysis()` / `get_analysis()` — vision result I/O

## PROFILE SYSTEM (infra/profile_json_store.py)

JSON file at `data/grok/profiles.json` (configurable via `profile.db_path`).

- `observe_user()` — records last-seen info on every trigger
- `get_profile()` / `upsert_profile()` / `delete_profile()`
- Auto-creates blank profiles on first contact (in orchestrator)
- Fields: username, preferred_name, group_nicknames, group_instruction,
  private_instruction, language_style, habit_preferences, muted

## VISION PIPELINE (vision/)

Requests flow through: quota check → cache lookup → model call → persist → return.

| File | Role |
|------|------|
| `client.py` | DashScope OpenAI-compatible client creation |
| `analyzer.py` | `analyze_image()` — routes to fast/detail/deep model |
| `video_analyzer.py` | `analyze_video()` — summary-only for now |
| `quota.py` | Per-user + global daily rate limiter |
| `schemas.py` | Pydantic `VisualAnalysis`, `normalize_analysis()`, `render_visual_context()` |
| `video_schemas.py` | Pydantic `VideoAnalysis`, `normalize_video_analysis()`, `render_video_context()` |
| `image_prep.py` | Download, compress, format-validate source images |
| `prompts.py` | System prompts for fast/detail/deep models |

## INFRA FILE SUMMARY

| File | DB | Tables | Purpose |
|------|----|--------|---------|
| `infra/trace_store.py` | recorder DB | `agent_reply_traces` | Agent execution traces |
| `infra/conversation_store.py` | recorder DB | `agent_conversation_sessions` | Multi-turn transcript storage |
| `infra/profile_json_store.py` | JSON file `data/grok/profiles.json` | — | User profiles |
| `infra/recorder_bridge.py` | recorder DB | all recorder tables | Cross-plugin DB access |
| `models.py` | recorder DB | agent_reply_traces, agent_conversation_sessions, agent_profile_snapshots | grok's own ORM models |

## CONFIG (config/)

| File | Role |
|------|------|
| `schema.py` | `@dataclass` config types: `AgentPluginSettings`, `ModelConfig`, `VisionConfig`, etc. |
| `builder.py` | `build_config()` — raw dict → typed config, includes `is_chat_targeted()` |
| `validation.py` | Runtime validation (recorder_db must be absolute path) |

## LOGGING

- `agent/llm_chain_logger.py` — structured request/response logging per LLM call
- `agent/model_adapter.py` — tool-call / text-response logging with escaped previews
- `trigger/rules.py` — prefilter and decision logging
- `app/orchestrator.py` — orchestration lifecycle logging
- `app/runtime.py` — step-level execution logging

`agent/model_adapter.py:100` escapes newlines in text-preview logging:
`text[:120].replace("\n", "\\n")`.

## KEY CONVENTIONS

- **9 handler tools** (registered), **14 schemas** (5 for internal/metadata).
- **`type: ignore` banned** in runtime code. Test mocks may use `type: ignore[assignment]`.
- **Dynamic imports** only via `compat.import_sibling_plugin_module()` (never direct).
- **`plugin.py` is thin** — no business logic, only event routing + init/teardown.
- **Forward content** is read from recorder DB, never from `get_forward_msg` API.
- **Thinking mode** passes `extra_body={"thinking": {"type": "enabled"}}`.
- **Config is gitignored** — use `config.example.yaml` as template.

## TESTS (tests/)

100+ tests across 20 test files. Key areas:

| Test file | Coverage |
|-----------|----------|
| `test_context_tools.py` | track_reply, load_context, load_message, extract_forward |
| `test_orchestrator.py` | handle_event lifecycle, conversation persistence |
| `test_runtime.py` | AgentRuntime multi-turn loop |
| `test_prompt_template.py` / `test_prompt_synthesizer.py` | System prompt rendering |
| `test_media_tools.py` | read_picture, read_video (quota, cache, persist) |
| `test_profile_tools.py` | CRUD profile operations |
| `test_model_adapter.py` | Tool call parsing, malformed args |
| `test_trigger_rules.py` | Prefilter, cooldown, decision |
| `test_forward_integration.py` | Recorder→grok forward data visibility |
