from __future__ import annotations

import logging

from app.config.paths import launch_command
from app.constants import APP_ID
from app.platform.base import Platform, StartupResult

logger = logging.getLogger(APP_ID)


class StartupManager:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform

    def apply(self, enabled: bool) -> StartupResult:
        if not enabled:
            result = self.platform.disable_startup()
            if not result.ok:
                logger.error("Failed to remove Windows startup registration: %s", result.error)
            return result
        command = launch_command(background=True)
        result = self.platform.enable_startup(command)
        if not result.ok:
            logger.error("Failed to register Windows startup: %s", result.error)
        else:
            logger.info("Registered Windows startup: %s", result.command)
        return result
