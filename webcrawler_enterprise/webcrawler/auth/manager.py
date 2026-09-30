"""User authentication with forced first-login password change and master reset."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path

from webcrawler.db.database import Database, utcnow

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
MASTER_RESET_CODE = "NTZHSS"
PBKDF2_ITERATIONS = 200_000


@dataclass
class UserAccount:
    id: int
    username: str
    role: str
    must_change_password: bool


@dataclass
class AuthResult:
    ok: bool
    message: str = ""
    user: UserAccount | None = None


class AuthManager:
    """SQLite-backed auth for the desktop application."""

    def __init__(self, db: Database | None = None, db_path: Path | None = None) -> None:
        self.db = db or Database(db_path)
        self.ensure_default_admin()

    def ensure_default_admin(self) -> None:
        row = self.db.fetchone(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (DEFAULT_USERNAME,),
        )
        if row:
            return
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(DEFAULT_PASSWORD, salt)
        now = utcnow()
        self.db.execute(
            "INSERT INTO users "
            "(username, password_hash, salt, role, must_change_password, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (DEFAULT_USERNAME, password_hash, salt, "admin", now, now),
        )

    def authenticate(self, username: str, password: str) -> AuthResult:
        username = (username or "").strip()
        if not username or not password:
            return AuthResult(False, "Username and password are required.")
        row = self.db.fetchone(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        )
        if not row:
            return AuthResult(False, "Invalid username or password.")
        expected = row["password_hash"]
        actual = self._hash_password(password, row["salt"])
        if not hmac.compare_digest(expected, actual):
            return AuthResult(False, "Invalid username or password.")
        user = UserAccount(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            must_change_password=bool(row["must_change_password"]),
        )
        return AuthResult(True, "Authenticated", user)

    def change_password(
        self,
        username: str,
        current_password: str,
        new_password: str,
        confirm_password: str,
        *,
        require_current: bool = True,
    ) -> AuthResult:
        username = (username or "").strip()
        if not new_password or not confirm_password:
            return AuthResult(False, "New password is required.")
        if new_password != confirm_password:
            return AuthResult(False, "New password and confirmation do not match.")
        if len(new_password) < 6:
            return AuthResult(False, "New password must be at least 6 characters.")
        if new_password == DEFAULT_PASSWORD:
            return AuthResult(False, "Choose a password different from the default.")

        row = self.db.fetchone(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        )
        if not row:
            return AuthResult(False, "User not found.")

        if require_current:
            if not current_password:
                return AuthResult(False, "Current password is required.")
            actual = self._hash_password(current_password, row["salt"])
            if not hmac.compare_digest(row["password_hash"], actual):
                return AuthResult(False, "Current password is incorrect.")

        salt = secrets.token_hex(16)
        password_hash = self._hash_password(new_password, salt)
        now = utcnow()
        self.db.execute(
            "UPDATE users SET password_hash=?, salt=?, must_change_password=0, updated_at=? "
            "WHERE id=?",
            (password_hash, salt, now, row["id"]),
        )
        user = UserAccount(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            must_change_password=False,
        )
        return AuthResult(True, "Password updated.", user)

    def master_reset(self, reset_code: str) -> AuthResult:
        """Reset admin account using the master code. Restores admin/admin and forces change."""
        if (reset_code or "").strip() != MASTER_RESET_CODE:
            return AuthResult(False, "Invalid master reset code.")

        self.ensure_default_admin()
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(DEFAULT_PASSWORD, salt)
        now = utcnow()
        row = self.db.fetchone(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (DEFAULT_USERNAME,),
        )
        if not row:
            self.db.execute(
                "INSERT INTO users "
                "(username, password_hash, salt, role, must_change_password, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (DEFAULT_USERNAME, password_hash, salt, "admin", now, now),
            )
        else:
            self.db.execute(
                "UPDATE users SET password_hash=?, salt=?, role=?, must_change_password=1, "
                "updated_at=? WHERE id=?",
                (password_hash, salt, "admin", now, row["id"]),
            )
        return AuthResult(
            True,
            "Admin password reset to 'admin'. You must change it on next login.",
            UserAccount(
                id=row["id"] if row else 0,
                username=DEFAULT_USERNAME,
                role="admin",
                must_change_password=True,
            ),
        )

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            PBKDF2_ITERATIONS,
        ).hex()
