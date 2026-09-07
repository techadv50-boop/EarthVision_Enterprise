"""Allowlisted remote actions. User input is never executed as a shell string."""

from __future__ import annotations

REMOTE_ACTIONS = frozenset(
    {
        "check",
        "discover-databases",
        "backup",
        "cleanup",
        "dry-run",
        "restore-files",
        "restore-database",
        "restore-nginx",
        "nginx-test",
        "safety-dump",
        "security-audit",
        "security-rotate-token",
        "security-rollback",
    }
)


def is_allowed_remote_action(action: str) -> bool:
    return action in REMOTE_ACTIONS
