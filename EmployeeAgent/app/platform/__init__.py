from __future__ import annotations

import os

from app.platform.base import Platform
from app.platform.stub import StubPlatform


def create_platform() -> Platform:
    if os.name == "nt":
        from app.platform.windows import WindowsPlatform

        return WindowsPlatform()
    return StubPlatform()
