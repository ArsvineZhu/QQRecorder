from plugins.grok.agent.prompt import (
    build_model_messages,
    render_system_prompt,
    render_tool_access_block,
)
from plugins.grok.config import build_config
from plugins.grok.context.evidence import (
    AgentWorkingContext,
    ContextBundle,
    EvidenceBlock,
)


def test_render_system_prompt_uses_grok_template_text():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )

    rendered = render_system_prompt(
        settings,
        values={},
    )

    assert "AI 助手 Grok" in rendered
    assert "## 运行时身份（动态注入）" in rendered
    assert "你的 QQ/self_id：`unknown`" in rendered
    assert "不要把聊天记录" in rendered
    assert "默认只看到每个工具的用途摘要" in rendered
    assert "load_tool_guide" in rendered
    assert "获取更多信息" not in rendered
    assert "JSON 动态注入" not in rendered
    assert "## `load_tool_guide`" in rendered
    assert "## `terminate`" in rendered
    assert "群聊里没有人明确要你回答" in rendered
    assert "不消耗工具调用额度" in rendered
    assert "同一轮里不要用相同参数重复调用" in rendered
    assert "## `track_reply`" not in rendered
    assert "回复要短、快、有判断，适合插入群聊。" not in rendered


def test_render_system_prompt_uses_configured_assistant_name():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "prompt": {"assistant_name": "博士"},
        }
    )

    rendered = render_system_prompt(
        settings,
        values={},
    )

    assert "AI 助手 博士" in rendered
    assert "AI 助手 Grok" not in rendered


def test_render_tool_access_block_only_mentions_layered_loading():
    block = render_tool_access_block()

    assert "默认只看到每个工具的用途摘要" in block
    assert "工具不只用于获取信息" in block
    assert "load_tool_guide" in block
    assert "JSON 动态注入" not in block
    assert "## `track_reply`" not in block
    assert "如果已经返回空，不要重复调用" not in block


def test_build_model_messages_puts_scene_specific_instructions_in_user_context():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="30001",
            user_id="20001",
            current_message="看看这个",
            trigger_reason="prefix:/agent",
            bot_id="10000",
        )
    )

    messages = build_model_messages(working_context, settings)

    assert "你的 QQ/self_id：`10000`" in messages[0]["content"]
    assert "回复要短、快、有判断" not in messages[0]["content"]
    assert "# 本轮回复任务" in messages[1]["content"]
    assert "## 要回答的用户消息" in messages[1]["content"]
    assert "看看这个" in messages[1]["content"].split("## 会话元信息", 1)[0]
    assert "## 回复要求" not in messages[1]["content"]
    assert "请生成一条可以直接发送到 IM 平台的回复" not in messages[1]["content"]
    assert "---\n\n## 工具数据" in messages[1]["content"]
    assert "- 本轮工具总额度：`0`" in messages[1]["content"]
    assert "- 当前剩余额度：`0`" in messages[1]["content"]


def test_build_model_messages_appends_tool_budget_block():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="30001",
            user_id="20001",
            current_message="看看这个",
            trigger_reason="prefix:/agent",
            bot_id="10000",
        ),
        tool_call_budget_total=6,
        tool_call_budget_remaining=4,
    )

    messages = build_model_messages(working_context, settings)

    assert "---\n\n## 工具数据" in messages[1]["content"]
    assert "- 本轮工具总额度：`6`" in messages[1]["content"]
    assert "- 当前剩余额度：`4`" in messages[1]["content"]


def test_build_model_messages_semanticizes_current_message_and_group_roster():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "prompt": {"assistant_name": "博士"},
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="1101497265",
            user_id="2162371684",
            current_message="[CQ:reply,id=473803557][CQ:at,qq=3644596926] 回答他",
            trigger_reason="group_at_bot",
            bot_id="3644596926",
            current_sender="Zodiac",
            current_time="2026-06-05 10:18:57",
        ),
        evidence=[
            EvidenceBlock(
                kind="tool_result",
                label="load_context",
                content=(
                    '{"status":"ok","data":{"messages":['
                    '{"timestamp":"2026-06-05 10:12:50","user_id":"2162371684",'
                    '"nickname":"Zodiac","raw_message":"别急我查 bug 呢",'
                    '"has_image":false,"has_forward":false},'
                    '{"timestamp":"2026-06-05 10:12:36","user_id":"64815614",'
                    '"nickname":"Man","raw_message":"[CQ:at,qq=3644596926] man",'
                    '"has_image":false,"has_forward":false}'
                    "]}}"
                ),
            )
        ],
    )

    messages = build_model_messages(working_context, settings)
    user_content = messages[1]["content"]

    assert "[CQ:reply,id=473803557]" not in user_content
    assert "[CQ:at,qq=3644596926]" not in user_content
    assert "> [回复:473803557] @博士 回答他" in user_content
    assert "## 群聊档案" in user_content
    assert "- `Zodiac` → `2162371684`" in user_content
    assert "- `Man` → `64815614`" in user_content
    assert "- `Man`\n  [10:12:36] @博士 man" in user_content


def test_build_model_messages_semanticizes_context_messages_and_reduces_image_metadata(  # noqa: E501
):
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="1101497265",
            user_id="2162371684",
            current_message="看看上一张图",
            trigger_reason="group_at_bot",
            bot_id="3644596926",
            current_sender="Zodiac",
        ),
        evidence=[
            EvidenceBlock(
                kind="tool_result",
                label="load_context",
                content=(
                    '{"status":"ok","data":{"messages":['
                    '{"timestamp":"2026-06-05 09:27:30","user_id":"64815614",'
                    '"nickname":"Man",'
                    '"raw_message":"[CQ:image,file=958AB7A44E9F5B09D6E268E12731F92D.jpg,sub_type=0,url=https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=abc,file_size=36113]（图片）",'
                    '"has_image":true,"has_forward":false}'
                    "]}}"
                ),
            )
        ],
    )

    messages = build_model_messages(working_context, settings)
    user_content = messages[1]["content"]

    assert "multimedia.nt.qq.com.cn" not in user_content
    assert "fileid=abc" not in user_content
    assert "[CQ:image" not in user_content
    assert "- `Man`\n  [09:27:30] [图片:类型:jpg,大小:36113] （图片）" in user_content


def test_build_model_messages_keeps_profile_instruction_without_reply_requirement_section():  # noqa: E501
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    instruction = (
        "回复要短、快、有判断，适合插入群聊。不要长篇解释；"
        "除非用户明确要求详细分析，否则控制在 1 到 4 句话。"
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="1101497265",
            user_id="2162371684",
            current_message="回答他",
            trigger_reason="group_at_bot",
            bot_id="3644596926",
            current_sender="Zodiac",
            group_instruction=instruction,
        ),
        evidence=[
            EvidenceBlock(
                kind="tool_result",
                label="load_profile",
                content=(
                    '{"status":"ok","data":{'
                    '"username":"Zodiac",'
                    '"preferred_name":"Arsvine",'
                    f'"group_instruction":"{instruction}",'
                    '"language_style":"专业可靠",'
                    '"group_nickname":"Zodiac"'
                    "}}"
                ),
            )
        ],
    )

    messages = build_model_messages(working_context, settings)
    user_content = messages[1]["content"]

    assert "### 用户档案" in user_content
    assert f"- **群聊指令**：{instruction}" in user_content
    assert user_content.count(instruction) == 1
    assert "## 回复要求" not in user_content
    assert "请生成一条可以直接发送到 IM 平台的回复" not in user_content
    assert "## 相关上下文\n### 用户档案" in user_content


def test_build_model_messages_groups_consecutive_context_messages_by_sender():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="1101497265",
            user_id="2162371684",
            current_message="博士测试",
            trigger_reason="group_at_bot",
            bot_id="3644596926",
            current_sender="Zodiac",
        ),
        evidence=[
            EvidenceBlock(
                kind="tool_result",
                label="load_context",
                content=(
                    '{"status":"ok","data":{"messages":['
                    '{"message_id":"m-a","timestamp":"2026-06-05 10:44:32",'
                    '"user_id":"64815614",'
                    '"nickname":"Consciencieux",'
                    '"raw_message":"@Grok 服务器到底有没有问题",'
                    '"has_image":false,"has_forward":false},'
                    '{"message_id":"m-b","timestamp":"2026-06-05 10:44:10",'
                    '"user_id":"64815614",'
                    '"nickname":"Consciencieux",'
                    '"raw_message":"@Grok 服务器修好了",'
                    '"has_image":false,"has_forward":false},'
                    '{"message_id":"m-c","timestamp":"2026-06-05 10:43:41",'
                    '"user_id":"3980072605",'
                    '"nickname":"明日から本気出す",'
                    '"raw_message":"@Grok 服务器繁忙",'
                    '"has_image":false,"has_forward":false}'
                    "]}}"
                ),
            )
        ],
    )

    user_content = build_model_messages(working_context, settings)[1]["content"]

    assert (
        "- `Consciencieux`\n"
        "  [10:44:32] @Grok 服务器到底有没有问题\n"
        "  [10:44:10] @Grok 服务器修好了" in user_content
    )
    assert "- `明日から本気出す`\n  [10:43:41] @Grok 服务器繁忙" in user_content


def test_build_model_messages_truncates_long_context_message_with_msg_id_hint():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
            "prompt": {"context_message_preview_chars": 80},
        }
    )
    long_text = "以下是热点新闻 " + ("国际局势 " * 80) + "需要我展开吗"
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="1101497265",
            user_id="2162371684",
            current_message="博士测试",
            trigger_reason="group_at_bot",
            bot_id="3644596926",
            current_sender="Zodiac",
        ),
        evidence=[
            EvidenceBlock(
                kind="tool_result",
                label="load_context",
                content=(
                    '{"status":"ok","data":{"messages":['
                    '{"message_id":"m-long",'
                    '"timestamp":"2026-06-05 10:47:42",'
                    '"user_id":"3980072605",'
                    '"nickname":"明日から本気出す",'
                    '"raw_message":"'
                    + long_text
                    + '","has_image":false,"has_forward":false}'
                    "]}}"
                ),
            )
        ],
    )

    user_content = build_model_messages(working_context, settings)[1]["content"]

    assert "[已截断，msg-id: `m-long`]" in user_content
    assert (
        "国际局势 国际局势 国际局势 国际局势 国际局势 国际局势"
        " 国际局势 国际局势 国际局势 国际局势 国际局势 国际局势 国际局势"
        not in user_content
    )
    assert "需要我展开吗" not in user_content


def test_build_model_messages_renders_load_message_expansion():
    settings = build_config(
        {
            "enabled": True,
            "recorder_db": "C:/tmp/recorder.db",
        }
    )
    working_context = AgentWorkingContext(
        context=ContextBundle(
            chat_type="group",
            chat_id="1101497265",
            user_id="2162371684",
            current_message="展开看看",
            trigger_reason="group_at_bot",
            bot_id="3644596926",
            current_sender="Zodiac",
        ),
        evidence=[
            EvidenceBlock(
                kind="tool_result",
                label="load_message",
                content=(
                    '{"status":"ok","data":{"message":{'
                    '"message_id":"m-long",'
                    '"timestamp":"2026-06-05 10:47:42",'
                    '"user_id":"3980072605",'
                    '"nickname":"明日から本気出す",'
                    '"raw_message":"这里是被展开的完整长消息",'
                    '"has_image":false,'
                    '"has_forward":false'
                    "}}}"
                ),
            )
        ],
    )

    user_content = build_model_messages(working_context, settings)[1]["content"]

    assert "## 相关上下文" in user_content
    assert "### 指定消息" in user_content
    assert "- msg-id：`m-long`" in user_content
    assert "- [10:47:42] `明日から本気出す`：这里是被展开的完整长消息" in user_content
