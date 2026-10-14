"""Plugin permission allowlist — deny unrestricted host access."""

from __future__ import annotations

# Explicitly allowed capability tokens for P1 plugins.
ALLOWED_PERMISSIONS = frozenset(
    {
        "synthetic_data",
        "ui.slot.left_toolbar",
        "ui.slot.right_analysis_panel",
        "ui.slot.map_overlay",
        "ui.slot.results_panel",
        "host.sdk.read_meta",
    }
)

# Hard rejects — never grant these in P1.
FORBIDDEN_PERMISSIONS = frozenset(
    {
        "filesystem",
        "filesystem.write",
        "filesystem.read",
        "network",
        "network.egress",
        "database",
        "database.write",
        "database.read",
        "shell",
        "subprocess",
        "admin",
        "arbitrary_code",
    }
)


def validate_permissions(requested: list[str] | None) -> list[str]:
    perms = [str(p).strip() for p in (requested or []) if str(p).strip()]
    bad = [p for p in perms if p in FORBIDDEN_PERMISSIONS or p not in ALLOWED_PERMISSIONS]
    if bad:
        raise ValueError(f"invalid or forbidden permissions: {bad}")
    return perms
