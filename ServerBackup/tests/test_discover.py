from pathlib import Path

from app.database.discover import discover_databases
from tests.helpers import FakeSSH, make_config


def test_discover_databases_does_not_hardcode_names(tmp_path: Path):
    cfg = make_config(tmp_path, selected_databases=[])
    rows = discover_databases(cfg, client=FakeSSH())
    names = [row["name"] for row in rows]
    assert "journal" in names
    assert "information_schema" in names
    system = [row for row in rows if row["name"] == "information_schema"][0]
    assert system["system"] is True
