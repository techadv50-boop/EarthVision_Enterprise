"""Network connectivity helpers for offline wait/resume."""

from __future__ import annotations

import socket
from urllib.parse import urlparse

import httpx


def is_online(probe_url: str | None = None, timeout: float = 5.0) -> bool:
    """Best-effort connectivity check (LAN DNS + well-known hosts)."""
    hosts: list[str] = []
    if probe_url:
        try:
            host = urlparse(probe_url).hostname
            if host:
                hosts.append(host)
        except Exception:
            pass
    hosts.extend(["1.1.1.1", "8.8.8.8", "dns.google"])

    for host in hosts:
        for port in (443, 80, 53):
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except OSError:
                continue

    if probe_url:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, verify=False) as client:
                client.head(probe_url)
                return True
        except Exception:
            return False
    return False


def is_connectivity_error(message: str | None) -> bool:
    """True when an exception text looks like offline / connection drop."""
    if not message:
        return False
    text = message.lower()
    needles = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "name or service not known",
        "getaddrinfo failed",
        "nodename nor servname",
        "network is unreachable",
        "connection refused",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "remote protocol error",
        "connect error",
        "connecttimeout",
        "readtimeout",
        "proxy error",
        "ssl",
        "errno 10054",
        "errno 10060",
        "errno 11001",
        "winerror 10054",
        "winerror 10060",
    )
    return any(n in text for n in needles)
