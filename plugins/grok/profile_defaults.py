from __future__ import annotations


def build_default_profile(
    *,
    user_id: str,
    chat_type: str,
    chat_id: str = "",
    sender_nickname: str = "",
    sender_card: str = "",
) -> dict:
    group_instr = (
        "回复要短、快、有判断，适合插入群聊。不要长篇解释；"
        "除非用户明确要求详细分析，否则控制在 1 到 4 句话。"
    )
    private_instr = (
        "回复更完整，但仍然保持直接、有判断、机智能给结论就先给结论，必要时再解释。"
    )
    record: dict = {
        "user_id": str(user_id),
        "username": (sender_nickname or sender_card or user_id)[:100],
        "preferred_name": "",
        "group_instruction": group_instr if chat_type == "group" else private_instr,
        "private_instruction": private_instr,
        "language_style": "",
        "habit_preferences": [],
        "group_nicknames": {},
        "private_nickname": "",
        "last_private_seen_at": "",
        "last_seen_at": "",
        "last_seen_chat_type": "",
        "last_seen_chat_id": "",
    }
    if chat_type == "group" and chat_id and sender_card:
        record["group_nicknames"] = {str(chat_id): sender_card[:100]}
    return record
