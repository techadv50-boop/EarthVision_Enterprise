"""Stage-specific SSH timeouts.

ConnectTimeout is only for login/reachability. Helper scripts and streams must
not inherit that short deadline as a total-command timeout. Streaming transfers
use an idle/inactivity timeout (and SSH keepalives) rather than a short total
elapsed timeout.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

# Actions that stream until the caller consumes stdout. Never give these a
# short total-command timeout; wait for idle/connection death instead.
STREAMING_ACTIONS = frozenset(
    {
        "stream-objects",
        "dump-databases",
        "backup",
    }
)

QUICK_ACTIONS = frozenset({"test_login", "printf", "connect", "ssh-test"})
INSTALL_ACTIONS = frozenset({"install_helper", "ensure_remote_scripts"})
DISCOVERY_ACTIONS = frozenset(
    {
        "discover-applications",
        "discover-ojs",
        "discover-databases",
    }
)
INVENTORY_ACTIONS = frozenset({"inventory", "hash-files"})
FINGERPRINT_ACTIONS = frozenset({"database-fingerprint"})
RESTORE_ACTIONS = frozenset(
    {
        "restore-files",
        "restore-database",
        "restore-nginx",
        "restore-complete",
        "restore-master",
        "safety-dump",
    }
)


class SSHCommandTimeout(RuntimeError):
    """Raised when an SSH command hits a stage timeout or goes idle."""

    def __init__(
        self,
        action: str,
        *,
        elapsed: float,
        last_activity: float,
        timeout: float | None = None,
        idle_timeout: float | None = None,
        bytes_seen: int = 0,
        kind: str = "command",
    ) -> None:
        self.action = action
        self.elapsed = elapsed
        self.last_activity = last_activity
        self.timeout = timeout
        self.idle_timeout = idle_timeout
        self.bytes_seen = bytes_seen
        self.kind = kind
        idle_ago = max(0.0, elapsed - last_activity)
        if kind == "idle":
            detail = (
                f"elapsed={elapsed:.1f}s, idle_timeout={idle_timeout:.0f}s, "
                f"last_activity={idle_ago:.1f}s ago, bytes={bytes_seen}"
            )
        else:
            detail = (
                f"elapsed={elapsed:.1f}s, timeout={timeout:.0f}s, "
                f"last_activity={idle_ago:.1f}s ago, bytes={bytes_seen}"
            )
        super().__init__(f"SSH command timed out during {action} ({detail}).")


def command_timeout_for(action: str, config: Any, explicit: int | None = None) -> int:
    """Total wait for a batch (JSON) SSH command. Not used for streaming popen."""
    if explicit is not None:
        return max(1, int(explicit))
    name = str(action or "").strip() or "ssh-command"
    connect = max(1, int(getattr(config, "ssh_connect_timeout", 20) or 20))
    install = max(1, int(getattr(config, "ssh_install_timeout", 180) or 180))
    discovery = max(1, int(getattr(config, "ssh_discovery_timeout", 1800) or 1800))
    fingerprint = max(1, int(getattr(config, "ssh_fingerprint_timeout", 600) or 600))
    transfer = max(1, int(getattr(config, "transfer_timeout", 6 * 60 * 60) or 6 * 60 * 60))
    command = max(1, int(getattr(config, "ssh_command_timeout", 1800) or 1800))
    audit = max(1, int(getattr(config, "security_audit_timeout", 180) or 180))
    if name in QUICK_ACTIONS:
        return connect
    if name in INSTALL_ACTIONS:
        return install
    if name in DISCOVERY_ACTIONS:
        return discovery
    if name in INVENTORY_ACTIONS:
        return transfer
    if name in FINGERPRINT_ACTIONS:
        return fingerprint
    if name in STREAMING_ACTIONS or name in RESTORE_ACTIONS:
        return transfer
    if name in {"cleanup"}:
        return 120
    if name in {"check", "dry-run", "nginx-test"}:
        return 120
    if name in {"ensure-backup-mysql-user"}:
        return max(90, install)
    if name.startswith("security-"):
        return audit
    return command


def idle_timeout_for(action: str, config: Any) -> int:
    """Seconds with no stdout/activity before a streaming command is considered hung."""
    idle = max(1, int(getattr(config, "ssh_idle_timeout", 300) or 300))
    name = str(action or "")
    if name == "dump-databases":
        return max(idle, 900)
    return idle


def keepalive_interval(config: Any) -> int:
    return max(1, int(getattr(config, "ssh_keepalive_interval", 15) or 15))


def keepalive_count(config: Any) -> int:
    return max(1, int(getattr(config, "ssh_keepalive_count", 4) or 4))


def _is_timeout_exc(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if isinstance(exc, (TimeoutError, TimeoutError)):
        return True
    if name in {"timeout", "timeouterror", "sockettimeout"}:
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in name


class IdleTimeoutStream:
    """File-like wrapper: idle timeout between bytes, not a total elapsed deadline.

    A live stream that keeps producing data will not time out merely because the
    transfer has been running longer than ssh_connect_timeout. A hung command
    that produces no output is still terminated after idle_timeout seconds.
    """

    def __init__(
        self,
        raw: Any,
        *,
        action: str,
        idle_timeout: float,
        on_log: Callable[[str], None] | None = None,
        on_kill: Callable[[], None] | None = None,
        activity_log_every: float = 8.0,
    ) -> None:
        self._raw = raw
        self.action = action
        self.idle_timeout = float(idle_timeout)
        self._on_log = on_log
        self._on_kill = on_kill
        self._activity_log_every = activity_log_every
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._buf = bytearray()
        self._started = False
        self._closed = False
        self._eof = False
        self.started_at = time.monotonic()
        self.last_activity = 0.0
        self.bytes_seen = 0
        self._last_log_at = 0.0
        self._last_log_bytes = 0

    def _log(self, message: str) -> None:
        if self._on_log is not None:
            self._on_log(message)

    def _elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def _make_timeout(self) -> SSHCommandTimeout:
        return SSHCommandTimeout(
            self.action,
            elapsed=self._elapsed(),
            last_activity=self.last_activity,
            idle_timeout=self.idle_timeout,
            bytes_seen=self.bytes_seen,
            kind="idle",
        )

    def _fail_idle(self) -> None:
        if self._on_kill is not None:
            try:
                self._on_kill()
            except Exception:
                pass
        self._log(
            f"SSH_COMMAND_TIMEOUT action={self.action} elapsed={self._elapsed():.1f} "
            f"last_activity={self.last_activity:.1f} idle_timeout={self.idle_timeout:.0f} "
            f"bytes={self.bytes_seen}"
        )
        raise self._make_timeout()

    def _maybe_log_activity(self) -> None:
        now = time.monotonic()
        if self._last_log_at and (now - self._last_log_at) < self._activity_log_every:
            if self.bytes_seen - self._last_log_bytes < 1024 * 1024:
                return
        self._last_log_at = now
        self._last_log_bytes = self.bytes_seen
        self._log(
            f"SSH_COMMAND_ACTIVITY action={self.action} elapsed={self._elapsed():.1f} "
            f"bytes={self.bytes_seen} last_activity={self.last_activity:.1f}"
        )

    def _reader_loop(self) -> None:
        try:
            while True:
                chunk = self._raw.read(256 * 1024)
                if chunk is None:
                    chunk = b""
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", "replace")
                self._queue.put(("data", chunk))
                if not chunk:
                    return
        except Exception as exc:  # noqa: BLE001
            if _is_timeout_exc(exc):
                self._queue.put(("error", self._make_timeout()))
            else:
                self._queue.put(("error", exc))

    def _ensure_reader(self) -> None:
        if self._started:
            return
        self._started = True
        thread = threading.Thread(target=self._reader_loop, daemon=True, name=f"ssh-idle-{self.action}")
        thread.start()

    def _next_chunk(self) -> bytes:
        if self._eof:
            return b""
        self._ensure_reader()
        try:
            kind, payload = self._queue.get(timeout=self.idle_timeout)
        except queue.Empty:
            self._fail_idle()
            raise
        if kind == "error":
            if isinstance(payload, SSHCommandTimeout):
                if self._on_kill is not None:
                    try:
                        self._on_kill()
                    except Exception:
                        pass
                self._log(
                    f"SSH_COMMAND_TIMEOUT action={self.action} elapsed={self._elapsed():.1f} "
                    f"last_activity={self.last_activity:.1f} idle_timeout={self.idle_timeout:.0f} "
                    f"bytes={self.bytes_seen}"
                )
                raise payload
            raise payload
        data = payload or b""
        if not data:
            self._eof = True
            return b""
        self.bytes_seen += len(data)
        self.last_activity = self._elapsed()
        self._maybe_log_activity()
        return data

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        if size < 0:
            parts = [bytes(self._buf)]
            self._buf.clear()
            while True:
                chunk = self._next_chunk()
                if not chunk:
                    break
                parts.append(chunk)
            return b"".join(parts)
        while len(self._buf) < size:
            chunk = self._next_chunk()
            if not chunk:
                break
            self._buf.extend(chunk)
        out = bytes(self._buf[:size])
        del self._buf[: len(out)]
        return out

    def readline(self, size: int = -1) -> bytes:
        while b"\n" not in self._buf:
            chunk = self._next_chunk()
            if not chunk:
                break
            self._buf.extend(chunk)
            if size > 0 and len(self._buf) >= size:
                break
        if not self._buf:
            return b""
        newline = self._buf.find(b"\n")
        if newline == -1:
            if size > 0:
                take = min(size, len(self._buf))
            else:
                take = len(self._buf)
            out = bytes(self._buf[:take])
            del self._buf[:take]
            return out
        take = newline + 1
        if size > 0:
            take = min(take, size)
        out = bytes(self._buf[:take])
        del self._buf[:take]
        return out

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        closer = getattr(self._raw, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                return

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        line = self.readline()
        if not line:
            raise StopIteration
        return line
