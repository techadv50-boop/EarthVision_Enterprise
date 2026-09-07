from app.config.schema import AppConfig
from app.ssh.client import SSHClient


def test_password_is_not_stored_in_config():
    cfg = AppConfig()
    assert "password" not in cfg.to_dict()
    assert "ssh_password" not in cfg.to_dict()


def test_password_auth_disables_batchmode_and_stays_off_argv(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    cfg = AppConfig(ssh_username="zhzh", ssh_private_key_path="")
    client = SSHClient(cfg, password="super-secret")
    args = client._base_ssh_args()
    joined = " ".join(args)
    assert "BatchMode=yes" not in joined
    assert "BatchMode=no" in joined
    assert "super-secret" not in joined
    env = client.ssh_env()
    assert env.get("SSH_ASKPASS_REQUIRE") == "force"
    assert env.get("SERVERBACKUP_ASKPASS") == "super-secret"


def test_key_only_keeps_batchmode(monkeypatch):
    monkeypatch.setattr("app.ssh.client.shutil.which", lambda _name: "/usr/bin/ssh")
    cfg = AppConfig(ssh_username="zhzh", ssh_private_key_path="")
    client = SSHClient(cfg)
    args = client._base_ssh_args()
    assert "BatchMode=yes" in " ".join(args)
    assert "SERVERBACKUP_ASKPASS" not in client.ssh_env()
