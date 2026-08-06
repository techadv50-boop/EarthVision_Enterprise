"""Authentication tests."""

from pathlib import Path

from webcrawler.auth.manager import (
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    MASTER_RESET_CODE,
    AuthManager,
)
from webcrawler.db.database import Database


def test_default_admin_and_forced_change(tmp_path: Path):
    db = Database(tmp_path / "auth.db")
    auth = AuthManager(db)

    bad = auth.authenticate("admin", "wrong")
    assert not bad.ok

    first = auth.authenticate(DEFAULT_USERNAME, DEFAULT_PASSWORD)
    assert first.ok
    assert first.user is not None
    assert first.user.must_change_password is True
    assert first.user.role == "admin"

    changed = auth.change_password(
        DEFAULT_USERNAME,
        DEFAULT_PASSWORD,
        "SecurePass1",
        "SecurePass1",
    )
    assert changed.ok
    assert changed.user is not None
    assert changed.user.must_change_password is False

    assert not auth.authenticate(DEFAULT_USERNAME, DEFAULT_PASSWORD).ok
    again = auth.authenticate(DEFAULT_USERNAME, "SecurePass1")
    assert again.ok
    assert again.user.must_change_password is False


def test_master_reset_code(tmp_path: Path):
    db = Database(tmp_path / "reset.db")
    auth = AuthManager(db)
    auth.change_password(DEFAULT_USERNAME, DEFAULT_PASSWORD, "NewPass99", "NewPass99")
    assert auth.authenticate(DEFAULT_USERNAME, "NewPass99").ok

    fail = auth.master_reset("WRONG")
    assert not fail.ok

    ok = auth.master_reset(MASTER_RESET_CODE)
    assert ok.ok
    assert MASTER_RESET_CODE == "NTZHSS"

    reset_login = auth.authenticate(DEFAULT_USERNAME, DEFAULT_PASSWORD)
    assert reset_login.ok
    assert reset_login.user.must_change_password is True
    assert reset_login.user.role == "admin"
