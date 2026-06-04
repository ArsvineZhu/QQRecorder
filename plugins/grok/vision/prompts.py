from __future__ import annotations

from pathlib import Path

from ..shared import load_text_asset


def build_vision_messages(
    chat_context: str,
    current_time: str = "",
) -> list[dict[str, str | list]]:
    system = _load_prompt_template("vision_image_system.md").replace(
        "{{JSON_SCHEMA}}",
        load_text_asset("vision/visual_analysis.json"),
    )
    user_text = """分析图片的内容与语义含义。

当前时间：{current_time}

聊天上下文如下：
{chat_context}

图片：
*引用*

请只输出符合指定结构的 JSON。""".format(
        current_time=current_time or "未知",
        chat_context=chat_context or "（无上下文）",
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
