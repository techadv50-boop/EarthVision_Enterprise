"""Network connectivity helpers for offline wait/resume."""

from __future__ import annotations

import socket
from urllib.parse import urlparse


def is_online(probe_url: str | None = None, timeout: float = 1.0) -> bool:
    """Fast connectivity check — avoid long stalls during crawls."""
    hosts: list[str] = ["1.1.1.1", "8.8.8.8"]
    if probe_url:
        try:
            host = urlparse(probe_url).hostname
            if host:
                hosts.insert(0, host)
        except Exception:
            pass

    for host in hosts:
        for port in (443, 80):
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except OSError:
                continue
    return False


def is_connectivity_error(message: str | None) -> bool:
    """True when an exception text looks like offline / connection drop."""
    if not message:
        return False
    text = message.lower()
    needles = (
        "connecttimeout",
        "readtimeout",
        "timed out",
        "name or service not known",
        "getaddrinfo failed",
        "nodename nor servname",
        "network is unreachable",
        "connection refused",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "connect error",
        "errno 10054",
        "errno 10060",
        "errno 11001",
        "winerror 10054",
        "winerror 10060",
        "winerror 11001",
    )
    return any(n in text for n in needles)
