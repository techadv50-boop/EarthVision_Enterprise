from app.constants import ALREADY_RUNNING_MESSAGE
from app.runtime.instance import SingleInstanceLock


def test_second_instance_is_rejected(tmp_path):
    lock_file = tmp_path / "agent.lock"
    first = SingleInstanceLock(lock_file)
    second = SingleInstanceLock(lock_file)
    assert first.acquire() is True
    try:
        assert second.acquire() is False
        assert second.message == ALREADY_RUNNING_MESSAGE
    finally:
        first.release()
        second.release()


def test_lock_released_allows_new_instance(tmp_path):
    lock_file = tmp_path / "agent.lock"
    first = SingleInstanceLock(lock_file)
    assert first.acquire()
    first.release()
    second = SingleInstanceLock(lock_file)
    assert second.acquire()
    second.release()


def test_main_second_process_exits(tmp_path, monkeypatch):
    from app.main import main
    from app.config.paths import resolve_paths

    paths = resolve_paths(tmp_path / "agent-data")
    paths.ensure()
    held = SingleInstanceLock(paths.lock_file)
    assert held.acquire()
    try:
        code = main(["--data-dir", str(paths.root), "--status"])
        # --status does not take the mutex; simulate duplicate start without --status
        code = main(["--data-dir", str(paths.root), "--headless"])
        assert code == 1
    finally:
        held.release()
