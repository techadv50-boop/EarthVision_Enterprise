"""Poll drop folders and forward files that are new or changed."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from relay.config import Endpoint, Settings, Source
from relay.paths import PathError, check_relative, local_path_for, remote_join
from relay.remote import RemoteFile
from relay.store import Store

logger = logging.getLogger(__name__)

ConnectorFactory = Callable[[Endpoint], object]


@dataclass
class CycleStats:
    fetched: int = 0
    forwarded: int = 0
    unstable: int = 0
    swept: int = 0
    errors: int = 0


@dataclass
class _Ready:
    item: RemoteFile
    destinations: list[Endpoint]
    local_path: Path


@dataclass
class RelayService:
    settings: Settings
    store: Store
    connector_factory: ConnectorFactory
    clock: Callable[[], float] = time.time
    sleeper: Callable[[float], None] = time.sleep
    _stopped: bool = field(default=False, init=False)

    def run_forever(self) -> None:
        logger.info(
            "file relay started; polling every %s seconds",
            self.settings.poll_interval_seconds,
        )
        while not self._stopped:
            started = self.clock()
            try:
                self.run_once()
            except Exception:
                logger.exception("poll cycle failed")
            elapsed = self.clock() - started
            delay = self.settings.poll_interval_seconds - elapsed
            self.sleeper(delay if delay > 0 else 0)

    def stop(self) -> None:
        self._stopped = True

    def run_once(self) -> CycleStats:
        stats = CycleStats()
        for source in self.settings.sources:
            try:
                self._poll_source(source, stats)
            except Exception:
                logger.exception("source %s failed", source.endpoint.id)
                stats.errors += 1
        try:
            stats.swept = self.sweep()
        except Exception:
            logger.exception("local cleanup failed")
            stats.errors += 1
        logger.info(
            "cycle fetched=%s forwarded=%s unstable=%s swept=%s errors=%s",
            stats.fetched,
            stats.forwarded,
            stats.unstable,
            stats.swept,
            stats.errors,
        )
        return stats

    def sweep(self) -> int:
        """Delete local copies that have reached their one-day life. Remotes stay."""
        now = self.clock()
        staging = self.settings.staging_dir.resolve()
        removed = 0
        for copy in self.store.expired_locals(now):
            candidate = _staged_file(staging, Path(copy.local_path))
            if candidate is None:
                logger.error("refusing to delete %s outside staging", copy.local_path)
                continue
            try:
                if candidate.is_symlink() or candidate.exists():
                    candidate.unlink()
                _remove_empty_parents(candidate.parent, staging)
            except OSError:
                logger.exception("could not delete local copy %s", candidate)
                continue
            self.store.delete_local(copy.source_id, copy.relative_path)
            logger.info("deleted local copy %s", copy.relative_path)
            removed += 1
        return removed

    def _poll_source(self, source: Source, stats: CycleStats) -> None:
        destinations = list(self.settings.destinations_for(source))
        if not destinations:
            logger.warning("source %s has no destinations", source.endpoint.id)
            return
        source_id = source.endpoint.id
        with self.connector_factory(source.endpoint) as remote:  # type: ignore[attr-defined]
            listed = remote.list_files(source.endpoint.remote_dir)
            ready: list[_Ready] = []
            seen: set[str] = set()
            for item in listed:
                try:
                    check_relative(item.relative_path)
                except PathError:
                    logger.error("skipping unsafe path %r from %s", item.relative_path, source_id)
                    stats.errors += 1
                    continue
                if item.relative_path in seen:
                    logger.error("duplicate path %s from %s", item.relative_path, source_id)
                    stats.errors += 1
                    continue
                seen.add(item.relative_path)
                try:
                    prepared = self._prepare(source, remote, item, destinations, stats)
                except Exception:
                    logger.exception("failed to fetch %s from %s", item.relative_path, source_id)
                    stats.errors += 1
                    continue
                if prepared is not None:
                    ready.append(prepared)
            self.store.forget_missing_observations(source_id, seen)
        self._forward(source, ready, stats)

    def _prepare(
        self,
        source: Source,
        remote: object,
        item: RemoteFile,
        destinations: list[Endpoint],
        stats: CycleStats,
    ) -> _Ready | None:
        source_id = source.endpoint.id
        now = self.clock()
        stable = self.store.note_observation(
            source_id,
            item,
            now,
            self.settings.stability_seconds,
        )
        if not stable:
            logger.debug("waiting for %s from %s to finish uploading", item.relative_path, source_id)
            stats.unstable += 1
            return None
        pending = [
            dest
            for dest in destinations
            if not self.store.is_delivered(source_id, item, dest.id)
        ]
        if not pending:
            return None
        local = local_path_for(self.settings.staging_dir, source_id, item.relative_path)
        existing = self.store.get_local(source_id, item.relative_path)
        usable = (
            existing is not None
            and existing.size == item.size
            and existing.mtime_key == item.version_key
            and local.is_file()
            and local.stat().st_size == item.size
        )
        if not usable:
            if existing is not None and (
                existing.size != item.size or existing.mtime_key != item.version_key
            ):
                if local.exists() or local.is_symlink():
                    local.unlink()
            remote_path = remote_join(source.endpoint.remote_dir, item.relative_path)
            remote.download(remote_path, local, item.size)  # type: ignore[attr-defined]
            actual = local.stat().st_size
            if actual != item.size:
                raise OSError(
                    f"{item.relative_path} downloaded {actual} bytes, expected {item.size}"
                )
            ttl_seconds = self.settings.local_ttl_hours * 3600
            self.store.save_local(
                source_id,
                item,
                str(local),
                downloaded_at=now,
                expires_at=now + ttl_seconds,
            )
            stats.fetched += 1
            logger.info("fetched %s from %s (%s bytes)", item.relative_path, source_id, item.size)
        return _Ready(item=item, destinations=pending, local_path=local)

    def _forward(self, source: Source, ready: list[_Ready], stats: CycleStats) -> None:
        buckets: dict[str, list[_Ready]] = {}
        dest_by_id = {dest.id: dest for dest in self.settings.destinations}
        for item in ready:
            for dest in item.destinations:
                buckets.setdefault(dest.id, []).append(item)
        for dest_id, jobs in buckets.items():
            dest = dest_by_id[dest_id]
            try:
                with self.connector_factory(dest) as remote:  # type: ignore[attr-defined]
                    for job in jobs:
                        try:
                            remote.upload(  # type: ignore[attr-defined]
                                job.local_path,
                                remote_join(dest.remote_dir, job.item.relative_path),
                            )
                        except Exception:
                            logger.exception(
                                "failed to forward %s to %s",
                                job.item.relative_path,
                                dest_id,
                            )
                            stats.errors += 1
                            continue
                        self.store.mark_delivered(
                            source.endpoint.id,
                            job.item,
                            dest_id,
                            self.clock(),
                        )
                        stats.forwarded += 1
                        logger.info("forwarded %s to %s", job.item.relative_path, dest_id)
            except Exception:
                logger.exception("could not connect to destination %s", dest_id)
                stats.errors += 1


def _staged_file(staging: Path, raw: Path) -> Path | None:
    """Return the local file if it stays inside staging, without following a final symlink."""
    try:
        parent = raw.parent.resolve()
    except OSError:
        return None
    candidate = parent / raw.name
    if candidate == staging or staging not in candidate.parents:
        return None
    return candidate


def _remove_empty_parents(start: Path, staging: Path) -> None:
    current = start
    while current != staging and staging in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
