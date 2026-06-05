"""Group ban / unban handler — records mute state to the profile JSON store
and writes recallable events to the recorder database.

Business logic lives here, not in plugin.py.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("grok.ban_handler")


async def handle_group_ban(plugin, event) -> None:
    sub = str(getattr(event, "sub_type", "") or "")
    group_id = str(getattr(event, "group_id", "") or "")
    user_id = str(getattr(event, "user_id", "") or "")
    self_id = str(getattr(event, "self_id", "") or "")

    if user_id != self_id or not group_id:
        return

    profile = getattr(plugin, "_profile_json_store", None)
    bridge = getattr(plugin, "_bridge", None)
    storage = bridge.storage if bridge is not None else None

    if sub == "ban":
        await _handle_ban(profile, storage, user_id, group_id, event)
    elif sub == "lift_ban":
        await _handle_unban(profile, storage, user_id, group_id)


async def _handle_ban(profile, storage, user_id, group_id, event) -> None:
    duration_sec = int(getattr(event, "duration", 0) or 0)
    muted_until = time.time() + duration_sec

    if profile is not None:
        await profile.patch_profile(
            user_id,
            {"muted_until": muted_until, "muted_group": group_id},
        )

    if storage is not None:
        try:
            await storage.save_image_analysis(
                file_unique=f"__ban__{group_id}__{int(muted_until)}",
                model_used="__system__",
                analysis_json=(
                    '{"event":"group_ban",'
                    f'"group_id":"{group_id}",'
                    f'"duration_sec":{duration_sec},'
                    f'"sub_type":"ban"'
                    "}"
                ),
                media_type="system_notice",
                confidence=1.0,
                prompt_version="v1",
                schema_version="v1",
            )
            logger.info(
                "ban: muted group=%s duration=%ds until=%d (written to recorder)",
                group_id,
                duration_sec,
                muted_until,
            )
        except Exception as exc:
            logger.warning("ban: failed to write notice to recorder: %s", exc)


async def _handle_unban(profile, storage, user_id, group_id) -> None:
    if profile is not None:
        await profile.patch_profile(
            user_id,
            {},
            remove_keys=("muted_until", "muted_group"),
        )

    if storage is not None:
        try:
            await storage.save_image_analysis(
                file_unique=f"__unban__{group_id}__{int(time.time())}",
                model_used="__system__",
                analysis_json=(
                    '{"event":"group_ban",'
                    f'"group_id":"{group_id}",'
                    f'"sub_type":"lift_ban"'
                    "}"
                ),
                media_type="system_notice",
                confidence=1.0,
                prompt_version="v1",
                schema_version="v1",
            )
            logger.info("ban: unmuted group=%s (written to recorder)", group_id)
        except Exception as exc:
            logger.warning("ban: failed to write unban notice to recorder: %s", exc)
