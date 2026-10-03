"""Reuse HTTP clients across a long crawl.

Opening a new connection for every page exhausts Windows sockets after
many hours (WinError 10055 / too many open files on Windows 7 and 10).
"""

from __future__ import annotations

import threading

import httpx


class ClientPool:
    """One httpx client per thread, closed together when the site crawl ends."""

    def __init__(self, **client_kwargs) -> None:
        self._kwargs = client_kwargs
        self._local = threading.local()
        self._all: list[httpx.Client] = []
        self._lock = threading.Lock()
        self._closed = False

    def client(self) -> httpx.Client:
        if self._closed:
            raise RuntimeError("HTTP client pool is closed")
        current = getattr(self._local, "client", None)
        if current is not None and not current.is_closed:
            return current
        created = httpx.Client(**self._kwargs)
        self._local.client = created
        with self._lock:
            self._all.append(created)
        return created

    def close(self) -> None:
        with self._lock:
            self._closed = True
            clients = list(self._all)
            self._all.clear()
        self._local.client = None
        for item in clients:
            try:
                item.close()
            except Exception:
                pass
