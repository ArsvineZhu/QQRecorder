from types import SimpleNamespace

from plugins.grok.trigger.rules import CooldownTracker, final_decision


def test_reply_to_bot_falls_back_to_recorded_reply_rows():
    source_msg = SimpleNamespace(
        replies=[SimpleNamespace(reply_to_message_id="bot-msg-1")]
    )
    settings = SimpleNamespace(trigger=SimpleNamespace(allow_reply_to_bot=True))

    allowed, reason = final_decision(
        event=SimpleNamespace(message=None),
        source_msg=source_msg,
        prefilter_reason=None,
        settings=settings,
        cooldowns=CooldownTracker(),
        bot_reply_message_ids={"bot-msg-1"},
    )

    assert allowed is True
    assert reason == "reply_to_bot"
