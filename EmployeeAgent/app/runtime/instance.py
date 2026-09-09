"""OS-level single-instance lock. Named mutex on Windows; fcntl elsewhere."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.constants import ALREADY_RUNNING_MESSAGE, MUTEX_NAME

ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    """Hold a named mutex (Windows) or an exclusive file lock (POSIX).

    Process-list checks are not used as the primary mechanism.
    """

    def __init__(self, lock_file: Path, mutex_name: str = MUTEX_NAME) -> None:
        self.lock_file = Path(lock_file)
        self.mutex_name = mutex_name
        self._handle = None
        self._fd: int | None = None
        self.acquired = False
        self.message = ALREADY_RUNNING_MESSAGE

    def acquire(self) -> bool:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            self.acquired = self._acquire_mutex()
            return self.acquired
        self.acquired = self._acquire_file()
        return self.acquired

    def release(self) -> None:
        if os.name == "nt":
            self._release_mutex()
        else:
            self._release_file()
        self.acquired = False

    def _acquire_mutex(self) -> bool:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        last_error = kernel32.GetLastError()
        if not handle:
            return self._acquire_file()
        self._handle = handle
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            self._handle = None
            return False
        self._write_pid()
        return True

    def _release_mutex(self) -> None:
        if not self._handle:
            return
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.ReleaseMutex(self._handle)
        kernel32.CloseHandle(self._handle)
        self._handle = None

    def _acquire_file(self) -> bool:
        flags = os.O_CREAT | os.O_RDWR
        fd = os.open(self.lock_file, flags, 0o644)
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError:
                    os.close(fd)
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    return False
        except Exception:
            os.close(fd)
            return False
        self._fd = fd
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode("ascii"))
        return True

    def _release_file(self) -> None:
        if self._fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def _write_pid(self) -> None:
        try:
            self.lock_file.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire():
            raise RuntimeError(self.message)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
