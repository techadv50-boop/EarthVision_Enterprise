"""Settings package."""

from webcrawler.settings.manager import (
    APP_DATA_FOLDER,
    AppSettings,
    SettingsManager,
    app_data_dir,
    legacy_app_data_dir,
)

__all__ = [
    "APP_DATA_FOLDER",
    "AppSettings",
    "SettingsManager",
    "app_data_dir",
    "legacy_app_data_dir",
]
