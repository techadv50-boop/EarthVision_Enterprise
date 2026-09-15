"""Parse OJS config.inc.php and validate discovered files_dir paths.

Never fall back to /var/www/ojs-files. A missing files_dir is a hard failure.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.security.paths import PathValidationError, validate_unix_path

DEFAULT_FALLBACK = "/var/www/ojs-files"
REQUIRED_OJS_DOMAINS = frozenset({"journal.50sea.com", "journal.xdgen.com"})
_FILES_DIR = re.compile(r"^\s*files_dir\s*=\s*(.*)$", re.IGNORECASE)
_VERSION = re.compile(r"^\s*version\s*=\s*(.*)$", re.IGNORECASE)


class DiscoveryError(RuntimeError):
    pass


def _strip_value(raw: str) -> str:
    value = raw.strip()
    if ";" in value and not (value.startswith('"') or value.startswith("'")):
        value = value.split(";", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def parse_files_dir(config_text: str) -> str | None:
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")):
            continue
        match = _FILES_DIR.match(stripped)
        if not match:
            continue
        value = _strip_value(match.group(1))
        return value or None
    return None


def parse_ojs_version(config_text: str) -> str:
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#", "//")):
            continue
        match = _VERSION.match(stripped)
        if match:
            value = _strip_value(match.group(1))
            if value:
                return value
    return "unknown"


def resolve_files_dir(raw: str, application_path: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise DiscoveryError("OJS files_dir is empty.")
    if cleaned.startswith("/"):
        resolved = cleaned
    else:
        resolved = str(Path(application_path.rstrip("/")) / cleaned)
    try:
        return validate_unix_path(resolved, field="OJS files_dir")
    except PathValidationError as exc:
        raise DiscoveryError(str(exc)) from exc


def _domain_from_path(application_path: str) -> str:
    return Path(application_path.rstrip("/")).name


def is_required_ojs_application(application_path: str) -> bool:
    return _domain_from_path(application_path) in REQUIRED_OJS_DOMAINS


def validate_discovery(payload: dict[str, Any], *, website_directories: list[str]) -> list[dict[str, Any]]:
    """Fail closed: every OJS site must have a real files_dir. No silent default."""
    if not isinstance(payload, dict):
        raise DiscoveryError("OJS discovery failed.")
    rows = payload.get("installations")
    if not isinstance(rows, list):
        raise DiscoveryError(str(payload.get("error") or "OJS discovery returned no installation list."))
    by_app = {str(item.get("application_path") or "").rstrip("/"): item for item in rows if isinstance(item, dict)}
    validated: list[dict[str, Any]] = []
    errors: list[str] = []
    remote_errors = [str(item) for item in (payload.get("errors") or []) if item]
    errors.extend(remote_errors)
    for website in website_directories:
        app = website.rstrip("/")
        item = by_app.get(app)
        if not item:
            if is_required_ojs_application(app):
                errors.append(f"{app}: OJS config.inc.php was not discovered")
            continue
        raw = str(item.get("files_dir_raw") or item.get("files_dir") or "").strip()
        if not raw:
            errors.append(f"{app}: config.inc.php has no files_dir")
            continue
        try:
            resolved = resolve_files_dir(raw, app)
        except DiscoveryError as exc:
            errors.append(f"{app}: {exc}")
            continue
        if resolved == DEFAULT_FALLBACK and raw not in {DEFAULT_FALLBACK, DEFAULT_FALLBACK + "/"}:
            errors.append(
                f"{app}: refusing silent fallback to {DEFAULT_FALLBACK}; "
                f"configured files_dir is {raw!r}"
            )
            continue
        if not item.get("exists"):
            errors.append(f"{app}: files_dir {resolved} does not exist")
            continue
        record = dict(item)
        record["application_path"] = app
        record["files_dir"] = resolved
        record["domain"] = record.get("domain") or _domain_from_path(app)
        validated.append(record)
    if errors:
        raise DiscoveryError("OJS discovery failed: " + "; ".join(errors))
    if not payload.get("ok") and not validated:
        raise DiscoveryError(str(payload.get("error") or "OJS discovery failed."))
    return validated
