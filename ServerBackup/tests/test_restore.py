from app.restore.restore_engine import CONFIRMATION_PHRASE, RestoreEngine, RestoreError
from tests.helpers import make_config


def test_restore_requires_confirmation(tmp_path):
    cfg = make_config(tmp_path)
    engine = RestoreEngine(cfg)
    try:
        engine.restore(tmp_path, confirmation="yes", action="restore-files")
        assert False, "must require RESTORE"
    except RestoreError as exc:
        assert CONFIRMATION_PHRASE in str(exc)
