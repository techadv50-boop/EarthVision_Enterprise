from pathlib import Path

from app.config.schema import AppConfig
from app.ssh.keys import create_ed25519_key, default_private_key_path, normalize_private_key_path, user_home


def test_default_private_key_uses_userprofile(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "WinUser"))
    assert default_private_key_path() == tmp_path / "WinUser" / ".ssh" / "id_ed25519"
    assert user_home() == tmp_path / "WinUser"


def test_normalize_pub_file_to_private(tmp_path: Path):
    private = tmp_path / "id_ed25519"
    public = tmp_path / "id_ed25519.pub"
    private.write_text("private", encoding="utf-8")
    public.write_text("public", encoding="utf-8")
    assert normalize_private_key_path(str(public)) == str(private)


def test_legacy_username_zhz_maps_to_zhzh():
    cfg = AppConfig.from_dict({"ssh_username": "zhz"})
    assert cfg.ssh_username == "zhzh"


def test_create_ed25519_key_when_ssh_keygen_exists(tmp_path: Path):
    import shutil

    if not shutil.which("ssh-keygen"):
        return
    private = tmp_path / "id_ed25519"
    info = create_ed25519_key(private)
    assert private.is_file()
    assert Path(str(info["public"])).is_file()
    assert info["created"] is True
    again = create_ed25519_key(private)
    assert again["created"] is False
