#!/usr/bin/env python3
"""Additively merge Tool Pack keys into a live Docker Compose overlay.

Preserves all existing services, env vars, volumes, and networking.
Never replaces the live file with a generic repo template.

Usage (ops, after backup):
  python3 scripts/deploy_merge_compose_overlay.py \\
    --live /path/to/live/docker-compose.yml \\
    --patch deployment/production/compose.overlay.tool_packs.proposed.yml \\
    --out /path/to/merged/docker-compose.yml \\
    --backup /path/to/docker-compose.yml.pre-toolpacks

Refuse to write if --out would clobber --live without --backup.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("PyYAML required for compose overlay merge") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"compose root must be a mapping: {path}")
    return data


def _dump_yaml(data: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_compose(live: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge patch into live for Tool Pack keys only (additive)."""
    out = dict(live)

    # Top-level volumes: add missing only
    live_vols = dict(out.get("volumes") or {})
    for name, spec in (patch.get("volumes") or {}).items():
        if name in live_vols:
            # Keep existing volume definition (do not overwrite)
            continue
        live_vols[name] = spec if spec is not None else None
    if live_vols:
        out["volumes"] = live_vols

    live_services = dict(out.get("services") or {})
    patch_services = patch.get("services") or {}
    for svc_name, svc_patch in patch_services.items():
        if svc_name not in live_services:
            raise SystemExit(
                f"refusing to add new service {svc_name!r} via Tool Pack patch "
                "(only additive keys on existing services are allowed)"
            )
        if not isinstance(svc_patch, dict):
            raise SystemExit(f"invalid service patch for {svc_name}")
        svc = dict(live_services[svc_name] or {})

        # environment: add missing keys only (never overwrite existing)
        if "environment" in svc_patch:
            env = svc.get("environment")
            if env is None:
                env = {}
            if isinstance(env, list):
                # list form KEY=VAL — convert to dict for merge then keep dict
                as_dict: dict[str, Any] = {}
                for item in env:
                    if isinstance(item, str) and "=" in item:
                        k, v = item.split("=", 1)
                        as_dict[k] = v
                    else:
                        raise SystemExit("unsupported list environment entry")
                env = as_dict
            if not isinstance(env, dict):
                raise SystemExit("environment must be a mapping")
            env = dict(env)
            for k, v in (svc_patch.get("environment") or {}).items():
                if k in env:
                    continue  # preserve live value
                env[k] = v
            svc["environment"] = env

        # volumes: append missing mount specs (string equality)
        if "volumes" in svc_patch:
            vols = list(svc.get("volumes") or [])
            existing = {str(x) for x in vols}
            for item in svc_patch.get("volumes") or []:
                s = str(item)
                if s not in existing:
                    vols.append(item)
                    existing.add(s)
            svc["volumes"] = vols

        # Disallow other service keys in patch (fail closed)
        allowed = {"environment", "volumes"}
        extra = set(svc_patch.keys()) - allowed
        if extra:
            raise SystemExit(f"refusing non-additive service keys in patch: {sorted(extra)}")

        live_services[svc_name] = svc

    out["services"] = live_services
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", required=True, type=Path)
    ap.add_argument("--patch", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--backup", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.live.is_file():
        print(f"ERROR: live compose missing: {args.live}", file=sys.stderr)
        return 2
    if not args.patch.is_file():
        print(f"ERROR: patch missing: {args.patch}", file=sys.stderr)
        return 2

    live_sha = _sha(args.live)
    live = _load_yaml(args.live)
    patch = _load_yaml(args.patch)
    merged = merge_compose(live, patch)
    text = _dump_yaml(merged)

    if args.dry_run:
        print(text)
        print(f"# dry-run ok live_sha={live_sha}", file=sys.stderr)
        return 0

    if args.out.resolve() == args.live.resolve():
        if args.backup is None:
            print("ERROR: writing over --live requires --backup", file=sys.stderr)
            return 2
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.live, args.backup)
        print(f"backup={args.backup} sha256={_sha(args.backup)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    import json

    print(
        json.dumps(
            {
                "ok": True,
                "live_sha256": live_sha,
                "out": str(args.out),
                "out_sha256": _sha(args.out),
                "backup": str(args.backup) if args.backup else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
