"""Launch helpers — keep this build fully isolated from older installs."""

from __future__ import annotations

from webcrawler.settings.manager import app_data_dir, legacy_app_data_dir


def prepare_launch_session() -> dict:
    """Ensure we only use the v2 data directory; never import legacy state.

    Older builds stored login/queue/URLs under WebCrawlerEnterprise.
    This build uses WebCrawlerEnterprise_v2 exclusively and does not copy
    or open any files from the legacy folder.
    """
    data = app_data_dir()
    legacy = legacy_app_data_dir()
    legacy_present = legacy.exists()
    # Fresh store markers (informational only).
    marker = data / "ISOLATED_FROM_LEGACY.txt"
    if not marker.exists():
        marker.write_text(
            "This folder is private to WebCrawler Enterprise v2+.\n"
            "It does not read or copy %APPDATA%\\WebCrawlerEnterprise "
            "(the old program repository).\n",
            encoding="utf-8",
        )
    return {
        "isolated": True,
        "data_dir": str(data),
        "legacy_dir": str(legacy),
        "legacy_present": legacy_present,
        "imported_legacy": False,
        "login": "admin / admin (change required on first login)",
    }
