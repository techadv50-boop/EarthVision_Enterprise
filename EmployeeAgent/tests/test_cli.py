import json

from app.main import main


def test_version_cli(capsys):
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    assert "Employee Monitoring Agent" in out
    assert "1.0.0" in out


def test_status_cli_when_not_running(tmp_path, capsys):
    code = main(["--data-dir", str(tmp_path / "empty"), "--status"])
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["running"] is False
