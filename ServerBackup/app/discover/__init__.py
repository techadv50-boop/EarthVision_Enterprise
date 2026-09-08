"""Windows-side application discovery. Remote collection is read-only."""

from __future__ import annotations

from app.discover.engine import DiscoveryError, discover_applications
from app.discover.policy import approve_all_applications, load_policy, save_policy, set_approval
from app.discover.report import format_discovery_report

__all__ = [
    "DiscoveryError",
    "approve_all_applications",
    "discover_applications",
    "format_discovery_report",
    "load_policy",
    "save_policy",
    "set_approval",
]
