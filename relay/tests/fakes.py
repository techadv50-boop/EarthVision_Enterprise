"""In-memory remote servers for the relay tests."""

from __future__ import annotations

from pathlib import Path

from relay.remote import RemoteFile


class MemoryFS:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, float]] = {}
        self.uploads: list[str] = []
        self.downloads: list[str] = []
        self.fail_uploads = 0
        self.fail_connect = False

    def __enter__(self) -> MemoryFS:
        if self.fail_connect:
            raise ConnectionError("could not connect")
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def list_files(self, remote_dir: str) -> list[RemoteFile]:
        prefix = remote_dir.rstrip("/") + "/"
        found: list[RemoteFile] = []
        for path, (data, mtime) in sorted(self.files.items()):
            if path.startswith(prefix):
                relative = path[len(prefix) :]
                if relative:
                    found.append(RemoteFile(relative, len(data), mtime))
        return found

    def download(self, remote_path: str, local_path: Path, expected_size: int) -> None:
        data, _mtime = self.files[remote_path]
        if len(data) != expected_size:
            raise OSError(f"{remote_path} is {len(data)} bytes, expected {expected_size}")
        self.downloads.append(remote_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)

    def upload(self, local_path: Path, remote_path: str) -> None:
        if self.fail_uploads:
            self.fail_uploads -= 1
            raise ConnectionError(f"upload failed for {remote_path}")
        data = local_path.read_bytes()
        self.files[remote_path] = (data, 0.0)
        self.uploads.append(remote_path)
