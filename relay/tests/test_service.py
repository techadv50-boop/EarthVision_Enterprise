from pathlib import Path

import pytest

from relay.cli import main
from relay.config import Endpoint, Settings, Source
from relay.service import RelayService
from relay.store import Store
from tests.fakes import MemoryFS

HOUR = 3600


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _endpoint(endpoint_id: str, remote_dir: str, protocol: str = "sftp") -> Endpoint:
    return Endpoint(
        id=endpoint_id,
        protocol=protocol,  # type: ignore[arg-type]
        host="example.test",
        port=22 if protocol == "sftp" else 21,
        username="user",
        remote_dir=remote_dir,
        password="secret",
    )


def _service(
    tmp_path: Path,
    *,
    deliver_to: object = "all",
    stability: float = 0,
    ttl_hours: float = 24,
    destinations: list[Endpoint] | None = None,
) -> tuple[RelayService, dict[str, MemoryFS], Clock]:
    dests = destinations or [
        _endpoint("archive", "/srv/incoming"),
        _endpoint("shared-copy", "/home/copy/incoming", "ftps"),
    ]
    source = Source(
        endpoint=_endpoint("namecheap", "/home/cpanel/drop"),
        deliver_to=deliver_to,  # type: ignore[arg-type]
    )
    settings = Settings(
        poll_interval_seconds=60,
        local_ttl_hours=ttl_hours,
        stability_seconds=stability,
        staging_dir=tmp_path / "staging",
        database_path=tmp_path / "relay.db",
        sources=(source,),
        destinations=tuple(dests),
    )
    servers = {
        "namecheap": MemoryFS(),
        "archive": MemoryFS(),
        "shared-copy": MemoryFS(),
    }
    store = Store(settings.database_path)
    store.migrate()
    clock = Clock()
    service = RelayService(
        settings,
        store,
        connector_factory=lambda endpoint: servers[endpoint.id],
        clock=clock,
    )
    return service, servers, clock


def test_new_file_and_nested_zip_are_forwarded_once(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to=("archive",))
    source = servers["namecheap"]
    source.files["/home/cpanel/drop/notes.txt"] = (b"hello", 10)
    source.files["/home/cpanel/drop/album/a.zip"] = (b"zip-bytes", 11)

    first = service.run_once()
    assert first.fetched == 2
    assert first.forwarded == 2
    assert servers["archive"].files["/srv/incoming/notes.txt"][0] == b"hello"
    assert servers["archive"].files["/srv/incoming/album/a.zip"][0] == b"zip-bytes"
    assert servers["shared-copy"].uploads == []

    second = service.run_once()
    assert second.fetched == 0
    assert second.forwarded == 0
    assert source.downloads == [
        "/home/cpanel/drop/album/a.zip",
        "/home/cpanel/drop/notes.txt",
    ]


def test_changed_file_is_copied_again(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to=("archive",))
    source = servers["namecheap"]
    source.files["/home/cpanel/drop/notes.txt"] = (b"v1", 10)
    service.run_once()

    source.files["/home/cpanel/drop/notes.txt"] = (b"version-two", 20)
    stats = service.run_once()
    assert stats.fetched == 1
    assert stats.forwarded == 1
    assert servers["archive"].files["/srv/incoming/notes.txt"][0] == b"version-two"


def test_unstable_upload_waits_for_the_next_snapshot(tmp_path: Path) -> None:
    service, servers, clock = _service(tmp_path, deliver_to=("archive",), stability=60)
    source = servers["namecheap"]
    source.files["/home/cpanel/drop/notes.txt"] = (b"partial", 10)

    first = service.run_once()
    assert first.unstable == 1
    assert first.fetched == 0
    assert servers["archive"].uploads == []

    clock.advance(30)
    source.files["/home/cpanel/drop/notes.txt"] = (b"still-growing", 40)
    second = service.run_once()
    assert second.unstable == 1
    assert second.fetched == 0

    clock.advance(60)
    third = service.run_once()
    assert third.fetched == 1
    assert third.forwarded == 1
    assert servers["archive"].files["/srv/incoming/notes.txt"][0] == b"still-growing"


def test_failed_destination_is_retried_without_recopying_the_source(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to="all")
    servers["namecheap"].files["/home/cpanel/drop/notes.txt"] = (b"hello", 10)
    servers["shared-copy"].fail_uploads = 1

    first = service.run_once()
    assert first.fetched == 1
    assert first.forwarded == 1
    assert first.errors == 1
    assert servers["archive"].uploads == ["/srv/incoming/notes.txt"]
    assert servers["shared-copy"].uploads == []

    second = service.run_once()
    assert second.fetched == 0
    assert second.forwarded == 1
    assert second.errors == 0
    assert servers["shared-copy"].files["/home/copy/incoming/notes.txt"][0] == b"hello"
    assert servers["archive"].uploads == ["/srv/incoming/notes.txt"]
    assert servers["namecheap"].downloads == ["/home/cpanel/drop/notes.txt"]


def test_deliver_to_all_reaches_every_destination(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to="all")
    servers["namecheap"].files["/home/cpanel/drop/notes.txt"] = (b"hello", 10)
    stats = service.run_once()
    assert stats.forwarded == 2
    assert servers["archive"].files["/srv/incoming/notes.txt"][0] == b"hello"
    assert servers["shared-copy"].files["/home/copy/incoming/notes.txt"][0] == b"hello"


def test_destination_connection_failure_retries_later(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to=("archive",))
    servers["namecheap"].files["/home/cpanel/drop/notes.txt"] = (b"hello", 10)
    servers["archive"].fail_connect = True

    failed = service.run_once()
    assert failed.fetched == 1
    assert failed.forwarded == 0
    assert failed.errors == 1

    servers["archive"].fail_connect = False
    retried = service.run_once()
    assert retried.fetched == 0
    assert retried.forwarded == 1


def test_local_copy_expires_without_touching_remote_files(tmp_path: Path) -> None:
    service, servers, clock = _service(tmp_path, deliver_to=("archive",))
    servers["namecheap"].files["/home/cpanel/drop/notes.txt"] = (b"hello", 10)
    service.run_once()
    local = tmp_path / "staging" / "namecheap" / "notes.txt"
    assert local.read_bytes() == b"hello"

    clock.advance(24 * HOUR - 1)
    assert service.sweep() == 0
    assert local.exists()

    clock.advance(1)
    assert service.sweep() == 1
    assert not local.exists()
    assert servers["namecheap"].files["/home/cpanel/drop/notes.txt"][0] == b"hello"
    assert servers["archive"].files["/srv/incoming/notes.txt"][0] == b"hello"

    again = service.run_once()
    assert again.fetched == 0
    assert again.forwarded == 0
    assert servers["archive"].uploads == ["/srv/incoming/notes.txt"]


def test_source_deletion_does_not_delete_the_destination(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to=("archive",))
    servers["namecheap"].files["/home/cpanel/drop/notes.txt"] = (b"hello", 10)
    service.run_once()
    del servers["namecheap"].files["/home/cpanel/drop/notes.txt"]

    stats = service.run_once()
    assert stats.forwarded == 0
    assert servers["archive"].files["/srv/incoming/notes.txt"][0] == b"hello"
    assert servers["archive"].uploads == ["/srv/incoming/notes.txt"]


def test_source_outage_does_not_stop_the_cycle(tmp_path: Path) -> None:
    service, servers, _clock = _service(tmp_path, deliver_to=("archive",))
    servers["namecheap"].fail_connect = True
    stats = service.run_once()
    assert stats.errors == 1
    assert stats.fetched == 0


def test_run_forever_polls_then_waits(tmp_path: Path) -> None:
    service, _servers, _clock = _service(tmp_path, deliver_to=("archive",))
    waits: list[float] = []

    def sleeper(delay: float) -> None:
        waits.append(delay)
        service.stop()

    service.sleeper = sleeper
    service.run_forever()
    assert waits == [60]


def test_cli_once_uses_the_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_PASSWORD", "source-secret")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
poll_interval_seconds: 60
local_ttl_hours: 24
stability_seconds: 0
staging_dir: {tmp_path / "staging"}
database_path: {tmp_path / "relay.db"}
sources:
  - id: namecheap
    protocol: sftp
    host: server.example
    port: 21098
    username: cpanel
    password_env: SOURCE_PASSWORD
    remote_dir: /home/cpanel/drop
    deliver_to: archive
destinations:
  - id: archive
    protocol: sftp
    host: 203.0.113.10
    port: 22
    username: relay
    password: dest-secret
    remote_dir: /srv/incoming
""",
        encoding="utf-8",
    )
    source = MemoryFS()
    dest = MemoryFS()
    source.files["/home/cpanel/drop/notes.txt"] = (b"from-cli", 5)
    servers = {"namecheap": source, "archive": dest}

    assert main(["--config", str(config), "--once"], lambda endpoint: servers[endpoint.id]) == 0
    assert dest.files["/srv/incoming/notes.txt"][0] == b"from-cli"
