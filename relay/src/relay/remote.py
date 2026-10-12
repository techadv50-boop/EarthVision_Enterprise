"""A file seen in a remote drop folder."""

from __future__ import annotations

from dataclasses import dataclass

from relay.paths import mtime_key


@dataclass(frozen=True)
class RemoteFile:
    relative_path: str
    size: int
    mtime: float

    @property
    def version_key(self) -> str:
        return mtime_key(self.mtime)
