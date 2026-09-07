from app import __version__
from app.main import main


def test_version_cli(capsys):
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    assert __version__ in out
