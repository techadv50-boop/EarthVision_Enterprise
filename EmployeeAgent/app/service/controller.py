"""Password gate for dashboard, settings, and exit. Never stays unlocked."""

from __future__ import annotations

from app.security.password import hash_password, verify_password


class AccessController:
    def __init__(self, password_hash: str = "") -> None:
        self.password_hash = password_hash
        self.dashboard_open = False
        self.settings_open = False

    def has_password(self) -> bool:
        return bool(self.password_hash)

    def verify(self, password: str) -> bool:
        return verify_password(password, self.password_hash)

    def set_password(self, password: str) -> str:
        self.password_hash = hash_password(password)
        self.lock()
        return self.password_hash

    def open_dashboard(self, password: str) -> bool:
        if not self.verify(password):
            return False
        self.dashboard_open = True
        return True

    def close_dashboard(self) -> None:
        self.dashboard_open = False

    def open_settings(self, password: str) -> bool:
        if not self.verify(password):
            return False
        self.settings_open = True
        return True

    def close_settings(self) -> None:
        self.settings_open = False

    def authorize_exit(self, password: str) -> bool:
        return self.verify(password)

    def lock(self) -> None:
        self.dashboard_open = False
        self.settings_open = False
