from plugins.qq_grok_reply.delivery import split_text


def test_split_text_returns_single_chunk_for_short_input():
    assert split_text("你好，世界", max_chars=10, max_parts=2) == ["你好，世界"]


def test_split_text_prefers_sentence_boundaries():
    text = "第一句很短。\n第二句也不长。\n第三句刚好。"

    parts = split_text(text, max_chars=10, max_parts=3)

    assert parts == ["第一句很短。", "第二句也不长。", "第三句刚好。"]


def test_split_text_hard_truncates_when_max_parts_is_reached():
    text = "甲乙丙丁戊己庚辛壬癸" * 3

    parts = split_text(text, max_chars=8, max_parts=2)

    assert len(parts) == 2
    assert all(len(part) <= 8 for part in parts)
