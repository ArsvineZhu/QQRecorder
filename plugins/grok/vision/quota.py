"""In-memory daily quota tracker for vision analysis.

Tracks per-user-per-chat and global daily limits. Resets when the
calendar date changes. Designed for the MVP — no DB persistence,
resets on plugin restart.
"""

import logging
from datetime import date
from threading import Lock

from ..config import VisionConfig

logger = logging.getLogger("grok.vision.quota")


class VisionQuotaTracker:
    """Daily quota counter for image (and later video) analysis.

    Thread-safe via Lock. All counters live in memory; a restart
    resets them, which is acceptable for the MVP.
    """

    def __init__(self, config: VisionConfig):
        self._config = config
        self._lock = Lock()
        # Key: (date_str, user_id, chat_id) or (date_str, "__global__", "__image__")
        self._image_counters: dict[tuple[str, str, str], int] = {}
        self._video_counters: dict[tuple[str, str, str], int] = {}

    # -- Image quota --

    def check_and_consume_image(self, user_id: str, chat_id: str) -> bool:
        """Check and consume one image quota slot.

        Returns:
            True if the call is within quota (slot consumed).
            False if quota exhausted (no slot consumed).
        """
        today = date.today().isoformat()

        with self._lock:
            # Per-user-chat limit
            user_key = (today, user_id, chat_id)
            user_used = self._image_counters.get(user_key, 0)
            if user_used >= self._config.daily_limit_image_per_user_chat:
                return False

            # Global limit
            global_key = (today, "__global__", "__image__")
            global_used = self._image_counters.get(global_key, 0)
            if global_used >= self._config.daily_limit_image_global:
                return False

            self._image_counters[user_key] = user_used + 1
            self._image_counters[global_key] = global_used + 1
            return True

    # -- Video quota (Phase 2) --

    def check_and_consume_video(self, user_id: str, chat_id: str) -> bool:
        """Check and consume one video quota slot (Phase 2)."""
        today = date.today().isoformat()

        with self._lock:
            user_key = (today, user_id, chat_id)
            user_used = self._video_counters.get(user_key, 0)
            if user_used >= self._config.daily_limit_video_per_user_chat:
                return False

            global_key = (today, "__global__", "__video__")
            global_used = self._video_counters.get(global_key, 0)
            if global_used >= self._config.daily_limit_video_global:
                return False

            self._video_counters[user_key] = user_used + 1
            self._video_counters[global_key] = global_used + 1
            return True

    # -- Diagnostic helpers --

    def remaining_image(self, user_id: str, chat_id: str) -> int:
        """Return remaining per-user-chat image quota for today."""
        today = date.today().isoformat()
        with self._lock:
            used = self._image_counters.get((today, user_id, chat_id), 0)
            return max(0, self._config.daily_limit_image_per_user_chat - used)

    def reset(self):
        """Clear all counters (useful for tests)."""
        with self._lock:
            self._image_counters.clear()
            self._video_counters.clear()
