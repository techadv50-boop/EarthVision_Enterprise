"""One-time launch migrations so a new build does not inherit an old live session."""

from __future__ import annotations

from pathlib import Path

from webcrawler.auth.manager import MASTER_RESET_CODE, AuthManager
from webcrawler.db.database import Database
from webcrawler.queue.manager import QueueManager
from webcrawler.settings.manager import SettingsManager, app_data_dir

# Bump this when a release should open clean (default login, empty URLs, no auto-run).
SESSION_PROFILE = 3


def session_profile_path() -> Path:
    return app_data_dir() / "session_profile.txt"


def prepare_launch_session() -> dict:
    """Reset inherited old-program session once per SESSION_PROFILE.

    Returns info for optional UI notice.
    """
    marker = session_profile_path()
    try:
        previous = int(marker.read_text(encoding="utf-8").strip()) if marker.exists() else 0
    except ValueError:
        previous = 0

    if previous >= SESSION_PROFILE:
        return {"migrated": False, "previous": previous, "current": SESSION_PROFILE}

    # Restore default login for the "new program" experience.
    AuthManager(Database()).master_reset(MASTER_RESET_CODE)

    # Do not keep old unfinished crawls ready to auto-run.
    QueueManager(Database()).abandon_all_unfinished()

    settings_manager = SettingsManager()
    settings_manager.settings.last_urls = ""
    settings_manager.save()

    marker.write_text(str(SESSION_PROFILE), encoding="utf-8")
    return {
        "migrated": True,
        "previous": previous,
        "current": SESSION_PROFILE,
        "login": "admin / admin (change required on first login)",
    }
