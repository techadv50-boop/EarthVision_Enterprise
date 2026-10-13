"""Ed25519 signature verification for Tool Pack artifacts.

Pack digest (``sha256:…`` of SHA256SUMS) is signed. Production activation
requires a signature from an approved publisher listed in
``approved_publishers.json``.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from app.tools.pack_paths import publishers_path

# Never trusted in production profile
_PREVIEW_PUBLISHER_IDS = frozenset({"preview-dev"})


class PackSignatureError(Exception):
    """Missing, unauthorized, or invalid pack signature."""


def trust_profile() -> str:
    """``production`` | ``preview`` | ``dev`` (default production for fail-closed images)."""
    return (os.environ.get("EV_PACK_TRUST_PROFILE") or "production").strip().lower()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _is_preview_publisher(pub: dict[str, Any]) -> bool:
    pid = str(pub.get("id") or "")
    env = str(pub.get("environment") or "").lower()
    return pid in _PREVIEW_PUBLISHER_IDS or env == "preview"


def load_approved_publishers(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or publishers_path()
    if not p.is_file():
        raise PackSignatureError(f"approved publishers file missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    pubs = data.get("publishers") or []
    if not isinstance(pubs, list):
        raise PackSignatureError("publishers must be a list")
    enabled = [x for x in pubs if isinstance(x, dict) and x.get("enabled", True)]
    profile = trust_profile()
    if profile == "production":
        # Fail closed: never accept preview-dev / environment=preview
        enabled = [x for x in enabled if not _is_preview_publisher(x)]
        if not enabled:
            raise PackSignatureError(
                "production trust profile has no enabled non-preview publishers "
                f"(file={p}; set EV_PACK_PUBLISHERS to a production allowlist)"
            )
    elif not enabled:
        raise PackSignatureError(f"no approved publishers configured in {p}")
    return enabled


def generate_keypair() -> tuple[str, str]:
    """Return (private_b64, public_b64) for ops key minting."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b64(priv_bytes), _b64(pub_bytes)


def sign_digest(digest: str, private_key_b64: str) -> str:
    if not digest.startswith("sha256:"):
        raise PackSignatureError("digest must be sha256:…")
    priv = Ed25519PrivateKey.from_private_bytes(_b64decode(private_key_b64))
    sig = priv.sign(digest.encode("utf-8"))
    return _b64(sig)


def verify_digest_signature(
    digest: str,
    signature_b64: str,
    *,
    publisher_id: str | None = None,
    publishers_file: Path | None = None,
) -> dict[str, Any]:
    """Verify signature against approved publishers. Returns matching publisher."""
    pubs = load_approved_publishers(publishers_file)
    candidates = pubs
    if publisher_id:
        candidates = [p for p in pubs if p.get("id") == publisher_id]
        if not candidates:
            raise PackSignatureError(f"publisher not approved: {publisher_id}")

    sig = _b64decode(signature_b64)
    last_err: Exception | None = None
    for pub in candidates:
        try:
            key = Ed25519PublicKey.from_public_bytes(_b64decode(str(pub["public_key"])))
            key.verify(sig, digest.encode("utf-8"))
            return pub
        except (InvalidSignature, KeyError, ValueError) as exc:
            last_err = exc
            continue
    raise PackSignatureError(
        f"signature not valid for any approved publisher (last={last_err})"
    )


def write_signature_file(
    pack_root: Path,
    *,
    digest: str,
    signature: str,
    publisher_id: str,
) -> Path:
    payload = {
        "schema_version": 1,
        "digest": digest,
        "algorithm": "ed25519",
        "publisher_id": publisher_id,
        "signature": signature,
    }
    path = pack_root / "SIGNATURE.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_signature_file(pack_root: Path) -> dict[str, Any]:
    path = pack_root / "SIGNATURE.json"
    if not path.is_file():
        raise PackSignatureError(f"SIGNATURE.json missing in {pack_root}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("signature") or not data.get("digest") or not data.get("publisher_id"):
        raise PackSignatureError("SIGNATURE.json incomplete")
    return data
