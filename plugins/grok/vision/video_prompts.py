from __future__ import annotations

from pathlib import Path

from ..shared import load_text_asset


def build_video_messages(
    chat_context: str,
    current_time: str = "",
    title: str = "",
    intro: str = "",
) -> list[dict[str, str | list]]:
    system = _load_prompt_template("vision_video_system.md").replace(
        "{{JSON_SCHEMA}}",
        load_text_asset("vision/video_analysis.json"),
    )
    user_text = """请分析这个视频的内容与语义含义。

当前时间：{current_time}

聊天上下文如下：
{chat_context}

视频：
*引用*

基本信息：
标题：{title}
简介：{intro}

请只输出符合指定结构的 JSON。""".format(
        current_time=current_time or "未知",
        chat_context=chat_context or "（无上下文）",
        title=title or "（无标题）",
        intro=intro or "（无简介）",
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
            ],
        },
    ]


def _load_prompt_template(name: str) -> str:
    return (Path(__file__).resolve().parent.parent / "prompt" / name).read_text(
        encoding="utf-8"
    )
