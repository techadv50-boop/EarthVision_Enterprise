"""Admin-installable Host Python extras (no Docker image rebuild).

Libraries are installed into a persistent directory on the Host volume
(``EV_PYTHON_EXTRAS_DIR``, default ``/data/tool_packs/python_extras``) with
``pip install --target``. That path is prepended to ``sys.path`` at startup.

This is the supported way to add a prerequisite package for a future plugin
without rebuilding frontend/backend images — like adding a package in a local
Python environment. Admin-only; wheel upload preferred.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from loguru import logger

MANIFEST_NAME = "EV_INSTALLED.json"
MAX_WHEEL_BYTES = 80 * 1024 * 1024  # 80 MiB per uploaded file
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

# Optional PyPI install allowlist (still admin-only). Empty = wheel upload only
# unless EV_HOST_LIBS_ALLOW_PIP=1 and name is in this set.
PIP_ALLOWLIST = frozenset(
    {
        "spectral",
        "rasterstats",
        "mercantile",
        "rio-cogeo",
        "affine",
        "pywavelets",
        "imageio",
        "tifffile",
        "numba",
        "joblib",
        "tqdm",
        "pandas",
        "networkx",
        "whitebox",
    }
)


class HostLibraryError(ValueError):
    """Invalid or failed Host library install."""


def extras_dir() -> Path:
    raw = (
        os.environ.get("EV_PYTHON_EXTRAS_DIR")
        or os.environ.get("EV_HOST_PYTHON_EXTRAS")
        or "/data/tool_packs/python_extras"
    )
    return Path(raw)


def ensure_extras_on_sys_path() -> str:
    """Prepend extras dir to sys.path so installed libs import without rebuild."""
    root = extras_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = str(root.resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
        logger.info("Host Python extras on sys.path: {}", path)
    return path


def _manifest_path() -> Path:
    return extras_dir() / MANIFEST_NAME


def _load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.is_file():
        return {"schema_version": 1, "packages": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": 1, "packages": {}}
    if not isinstance(data, dict):
        return {"schema_version": 1, "packages": {}}
    data.setdefault("schema_version", 1)
    data.setdefault("packages", {})
    if not isinstance(data["packages"], dict):
        data["packages"] = {}
    return data


def _save_manifest(data: dict[str, Any]) -> None:
    root = extras_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = _manifest_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def list_installed() -> dict[str, Any]:
    ensure_extras_on_sys_path()
    man = _load_manifest()
    return {
        "ok": True,
        "extras_dir": str(extras_dir()),
        "on_sys_path": str(extras_dir().resolve()) in sys.path,
        "pip_allowlist": sorted(PIP_ALLOWLIST),
        "pip_from_index_enabled": os.environ.get("EV_HOST_LIBS_ALLOW_PIP", "0") == "1",
        "packages": man.get("packages") or {},
        "notes": (
            "Upload .whl files here to extend the Host without rebuilding images. "
            "After install, new imports work immediately for unloaded modules; "
            "if needed, restart the backend container (not rebuild)."
        ),
    }


def _run_pip(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", *args]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        raise HostLibraryError("pip install timed out") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "pip failed")[-2000:]
        raise HostLibraryError(f"pip failed: {err}")


def install_wheels(
    *,
    files: list[tuple[str, bytes]],
    actor: str,
) -> dict[str, Any]:
    """Install one or more wheel/sdist blobs into the extras target directory."""
    if not files:
        raise HostLibraryError("no library files provided")
    ensure_extras_on_sys_path()
    root = extras_dir()
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ev-host-libs-") as tmp:
        tmp_path = Path(tmp)
        paths: list[Path] = []
        for name, blob in files:
            base = Path(name).name
            if not base.lower().endswith((".whl", ".tar.gz", ".zip")):
                raise HostLibraryError(
                    f"unsupported library file {base!r}; upload .whl (preferred) or .tar.gz"
                )
            if len(blob) > MAX_WHEEL_BYTES:
                raise HostLibraryError(f"{base} exceeds {MAX_WHEEL_BYTES} bytes")
            if len(blob) < 64:
                raise HostLibraryError(f"{base} looks empty/invalid")
            dest = tmp_path / base
            dest.write_bytes(blob)
            paths.append(dest)

        _run_pip(
            [
                "install",
                "--target",
                str(root),
                "--upgrade",
                "--no-cache-dir",
                "--disable-pip-version-check",
                *[str(p) for p in paths],
            ]
        )

    man = _load_manifest()
    packages: dict[str, Any] = man.setdefault("packages", {})
    installed_names: list[str] = []
    for name, _blob in files:
        base = Path(name).name
        # Best-effort distribution name from wheel filename
        dist = base.split("-")[0].replace("_", "-").lower()
        packages[dist] = {
            "source": "wheel_upload",
            "filename": base,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor": actor,
        }
        installed_names.append(dist)
    man["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_manifest(man)

    return {
        "ok": True,
        "installed": installed_names,
        "extras_dir": str(root),
        "restart_hint": (
            "Libraries are on the persistent Host volume. "
            "No image rebuild. If an import fails in a long-lived worker, "
            "run: docker compose restart backend"
        ),
    }


def install_from_index(*, package: str, version: str | None, actor: str) -> dict[str, Any]:
    """Optional allowlisted pip install from index (disabled by default)."""
    if os.environ.get("EV_HOST_LIBS_ALLOW_PIP", "0") != "1":
        raise HostLibraryError(
            "PyPI install disabled. Upload a .whl instead, or set "
            "EV_HOST_LIBS_ALLOW_PIP=1 on the Host (admin policy)."
        )
    pkg = (package or "").strip()
    if not SAFE_NAME.match(pkg) or pkg.lower() not in {p.lower() for p in PIP_ALLOWLIST}:
        raise HostLibraryError(
            f"package {package!r} not in Host allowlist. "
            f"Allowed: {', '.join(sorted(PIP_ALLOWLIST))}"
        )
    if version is not None:
        ver = version.strip()
        if not re.match(r"^[A-Za-z0-9._+-]+$", ver):
            raise HostLibraryError("invalid version")
        spec = f"{pkg}=={ver}"
    else:
        spec = pkg

    ensure_extras_on_sys_path()
    root = extras_dir()
    root.mkdir(parents=True, exist_ok=True)
    _run_pip(
        [
            "install",
            "--target",
            str(root),
            "--upgrade",
            "--no-cache-dir",
            "--disable-pip-version-check",
            spec,
        ]
    )
    man = _load_manifest()
    packages: dict[str, Any] = man.setdefault("packages", {})
    key = pkg.lower().replace("_", "-")
    packages[key] = {
        "source": "pip_index",
        "spec": spec,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "actor": actor,
    }
    man["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_manifest(man)
    return {
        "ok": True,
        "installed": [key],
        "extras_dir": str(root),
        "restart_hint": "No image rebuild. Restart backend only if imports fail.",
    }


def uninstall_package(*, name: str, actor: str) -> dict[str, Any]:
    """Remove a distribution folder from the extras target (best-effort)."""
    key = (name or "").strip().lower().replace("_", "-")
    if not SAFE_NAME.match(key):
        raise HostLibraryError("invalid package name")
    ensure_extras_on_sys_path()
    root = extras_dir()
    removed: list[str] = []
    # Common pip --target layout: package dir + dist-info
    for child in list(root.iterdir()) if root.is_dir() else []:
        n = child.name.lower().replace("_", "-")
        if n == key or n.startswith(f"{key}-") and n.endswith(".dist-info"):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            removed.append(child.name)
        elif n.replace(".", "-") == key:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child.name)

    man = _load_manifest()
    packages: dict[str, Any] = man.setdefault("packages", {})
    if key in packages:
        packages.pop(key, None)
        man["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        man["last_uninstall"] = {"name": key, "actor": actor, "removed": removed}
        _save_manifest(man)
    return {"ok": True, "removed": removed, "name": key}
