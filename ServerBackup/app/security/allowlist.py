"""Allowlisted remote actions. User input is never executed as a shell string."""

from __future__ import annotations

REMOTE_ACTIONS = frozenset(
    {
        "check",
        "discover-databases",
        "backup",
        "cleanup",
        "dry-run",
        "discover-ojs",
        "inventory",
        "hash-files",
        "stream-objects",
        "database-fingerprint",
        "dump-databases",
        "restore-files",
        "restore-database",
        "restore-nginx",
        "restore-complete",
        "restore-master",
        "nginx-test",
        "safety-dump",
        "discover-applications",
        "security-audit",
        "security-rotate-token",
        "security-rollback",
    }
)


def is_allowed_remote_action(action: str) -> bool:
    return action in REMOTE_ACTIONS
