"""Ed25519 pack signature verification inside the worker (no Host Shell imports)."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_PREVIEW_IDS = frozenset({"preview-dev"})


class SignatureError(RuntimeError):
    """Missing or invalid publisher signature."""


def _b64decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def publishers_path() -> Path:
    override = os.environ.get("EV_PACK_PUBLISHERS")
    if override:
        return Path(override)
    root = os.environ.get("EV_TOOL_PACKS_ROOT") or os.environ.get("EV_ARTIFACTS_ROOT")
    if root:
        candidate = Path(root).parent / "publishers" / "approved_publishers.json"
        if candidate.is_file():
            return candidate
        # artifacts root case: …/artifacts → …/publishers
        p = Path(root)
        if p.name == "artifacts":
            return p.parent / "publishers" / "approved_publishers.json"
    raise SignatureError("EV_PACK_PUBLISHERS not configured")


def trust_profile() -> str:
    return (os.environ.get("EV_PACK_TRUST_PROFILE") or "production").strip().lower()


def load_publishers() -> list[dict[str, Any]]:
    path = publishers_path()
    if not path.is_file():
        raise SignatureError(f"publishers file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    pubs = [p for p in (data.get("publishers") or []) if isinstance(p, dict) and p.get("enabled", True)]
    if trust_profile() == "production":
        pubs = [
            p
            for p in pubs
            if str(p.get("id")) not in _PREVIEW_IDS
            and str(p.get("environment") or "").lower() != "preview"
        ]
    if not pubs:
        raise SignatureError("no enabled trusted publishers for worker trust profile")
    return pubs


def read_signature(pack_root: Path) -> dict[str, Any]:
    path = pack_root / "SIGNATURE.json"
    if not path.is_file() or path.is_symlink():
        raise SignatureError("SIGNATURE.json missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("digest", "signature", "publisher_id"):
        if not data.get(key):
            raise SignatureError(f"SIGNATURE.json missing {key}")
    return data


def verify_pack_signature(pack_root: Path, expected_digest: str) -> dict[str, Any]:
    """Verify Ed25519 signature over the pack digest against trusted publishers."""
    if os.environ.get("EV_PACK_REQUIRE_SIGNATURE", "1") == "0":
        raise SignatureError("worker refuses EV_PACK_REQUIRE_SIGNATURE=0 (fail closed)")
    sig = read_signature(pack_root)
    if sig["digest"] != expected_digest:
        raise SignatureError("SIGNATURE.json digest mismatch vs artifact digest")
    pubs = load_publishers()
    pub = next((p for p in pubs if str(p.get("id")) == str(sig["publisher_id"])), None)
    if pub is None:
        raise SignatureError(f"publisher not trusted: {sig['publisher_id']}")
    try:
        key = Ed25519PublicKey.from_public_bytes(_b64decode(str(pub["public_key"])))
        key.verify(_b64decode(str(sig["signature"])), expected_digest.encode("utf-8"))
    except (InvalidSignature, ValueError, KeyError) as exc:
        raise SignatureError(f"signature verification failed: {exc}") from exc
    return pub
