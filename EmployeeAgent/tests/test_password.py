from app.security.password import hash_password, password_is_hashed, verify_password


def test_password_is_not_stored_as_plaintext(password):
    stored = hash_password(password)
    assert password not in stored
    assert password_is_hashed(stored)
    assert stored.startswith("pbkdf2_sha256$")


def test_verify_accepts_only_correct_password(password):
    stored = hash_password(password)
    assert verify_password(password, stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("", stored)
    assert not verify_password(password, password)


def test_empty_password_rejected():
    import pytest
    from app.security.password import PasswordError

    with pytest.raises(PasswordError):
        hash_password("")


def test_config_file_never_contains_plaintext(tmp_path, clock, platform, password):
    from tests.conftest import build_service

    service = build_service(tmp_path, clock, platform, password)
    raw = service.paths.config_file.read_text(encoding="utf-8")
    assert password not in raw
    assert "pbkdf2_sha256$" in raw
