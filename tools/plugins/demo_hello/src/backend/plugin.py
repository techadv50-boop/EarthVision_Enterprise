"""Harmless demonstration plugin — synthetic data only (Stage P1).

No filesystem, network, or database access.
"""

from __future__ import annotations

from typing import Any

PLUGIN_ID = "demo_hello"
PACK_VERSION = "1.0.0"
MESSAGE_TAG = "demo_plugin"


def render(_request: Any = None) -> dict[str, Any]:
    """Return synthetic demonstration payload (no host imagery required)."""
    return {
        "kind": "synthetic_demo",
        "plugin_id": PLUGIN_ID,
        "version": PACK_VERSION,
        "message": "Hello from the SATEYE Plugin Manager demonstration pack.",
        "tag": MESSAGE_TAG,
        "points": [
            {"label": "Alpha", "value": 42},
            {"label": "Beta", "value": 17},
            {"label": "Gamma", "value": 3},
        ],
        "note": "This output is synthetic and does not touch legacy tools.",
    }
