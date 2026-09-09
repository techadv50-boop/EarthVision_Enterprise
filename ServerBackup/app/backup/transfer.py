"""Copy a remote streamed archive to the incomplete backup directory."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

CHUNK = 1024 * 1024


class TransferCancelled(RuntimeError):
    pass


def stream_copy(
    process: subprocess.Popen[bytes],
    destination: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, float], None] | None = None,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    started = time.monotonic()
    assert process.stdout is not None
    with destination.open("wb") as handle:
        while True:
            if should_cancel and should_cancel():
                process.kill()
                raise TransferCancelled("Backup cancelled during transfer.")
            chunk = process.stdout.read(CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
            elapsed = max(0.001, time.monotonic() - started)
            if on_progress:
                on_progress(written, written / elapsed)
    returncode = process.wait()
    if returncode != 0:
        stderr = b""
        if process.stderr:
            stderr = process.stderr.read() or b""
        message = stderr.decode("utf-8", errors="replace").strip() or f"exit {returncode}"
        raise RuntimeError(f"Backup transfer failed: {message}")
    return written


def poll_file_size(
    path: Path,
    process: subprocess.Popen,
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, float], None] | None = None,
    interval: float = 0.5,
) -> None:
    started = time.monotonic()
    last = 0

    def _loop() -> None:
        nonlocal last
        while process.poll() is None:
            if should_cancel and should_cancel():
                return
            try:
                size = path.stat().st_size if path.is_file() else 0
            except OSError:
                size = 0
            elapsed = max(0.001, time.monotonic() - started)
            if on_progress and size != last:
                on_progress(size, size / elapsed)
                last = size
            time.sleep(interval)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
