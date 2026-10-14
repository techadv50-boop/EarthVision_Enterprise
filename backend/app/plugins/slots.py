"""Supported frontend placement slots for plugins (Host Shell contract)."""

from __future__ import annotations

SUPPORTED_SLOTS = frozenset(
    {
        "left_toolbar",
        "right_analysis_panel",
        "map_overlay",
        "results_panel",
    }
)


def validate_slot(slot: str | None) -> str:
    if not slot or slot not in SUPPORTED_SLOTS:
        raise ValueError(
            f"invalid UI slot {slot!r}; supported: {', '.join(sorted(SUPPORTED_SLOTS))}"
        )
    return slot
