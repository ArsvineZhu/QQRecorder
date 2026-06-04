from plugins.grok.vision.prompts import build_vision_messages
from plugins.grok.vision.video_prompts import build_video_messages


def test_build_vision_messages_uses_local_prompt_and_json_asset():
    messages = build_vision_messages("用户说这图什么意思", "2026-06-04 12:00:00")
    content = messages[1]["content"]
    assert isinstance(content, list)
    text_part = content[0]
    assert isinstance(text_part, dict)

    assert "视觉语义解释器" in messages[0]["content"]
    assert (
        '"image_type": "meme / sticker / real_photo / screenshot / document / mixed"'
        in messages[0]["content"]
    )
    assert "{{JSON_SCHEMA}}" not in messages[0]["content"]
    assert "用户说这图什么意思" in str(text_part.get("text", ""))


def test_build_video_messages_uses_local_prompt_and_json_asset():
    messages = build_video_messages(
        "群里在讨论这个视频",
        "2026-06-04 12:00:00",
        "标题",
        "简介",
    )
    content = messages[1]["content"]
    assert isinstance(content, list)
    text_part = content[0]
    assert isinstance(text_part, dict)

    assert "视频语义解释器" in messages[0]["content"]
    assert '"media_type": "video"' in messages[0]["content"]
    assert '"time_range": {' in messages[0]["content"]
    assert '"start_time": "HH:MM:SS' in messages[0]["content"]
    assert "{{JSON_SCHEMA}}" not in messages[0]["content"]
    text = str(text_part.get("text", ""))
    assert "群里在讨论这个视频" in text
    assert "标题：标题" in text
