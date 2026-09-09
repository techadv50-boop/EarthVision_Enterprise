"""Classify security findings. Not every change is treated as malicious."""

from __future__ import annotations

from typing import Any

SEVERITIES = (
    "EXPECTED/APPROPRIATE",
    "LIKELY APPROPRIATE",
    "REQUIRES REVIEW",
    "SUSPICIOUS",
    "CRITICAL",
)

_CACHE_MARKERS = (
    "/cache/",
    "/tmp/",
    "/temp/",
    "/sessions/",
    "/session/",
    "/logs/",
    "/.git/",
    "/node_modules/",
    "/vendor/",
    "files/",
)
_LOG_SUFFIXES = (".log", ".tmp", ".swp", ".pid")
_EXPECTED_WEB_SUFFIXES = (
    ".php",
    ".js",
    ".css",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
    ".xml",
    ".json",
    ".txt",
    ".md",
    ".pdf",
    ".doc",
    ".docx",
)
_SCRIPT_SUFFIXES = (".sh", ".bash", ".py", ".pl", ".rb", ".exe", ".bin", ".elf")
_WEB_SHELL_HINTS = ("c99.php", "r57.php", "wso.php", "b374k", "eval(base64_decode")


def _path_is_cache(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _CACHE_MARKERS) or lowered.endswith(_LOG_SUFFIXES)


def _is_config_path(path: str) -> bool:
    return path.startswith("/etc/") or path.endswith(".conf") or "/nginx/" in path


def classify_change(change: dict[str, Any], *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the change with severity and reason. Does not mutate production."""
    kind = str(change.get("kind") or "")
    path = str(change.get("path") or "")
    layer = str(change.get("layer") or "3")
    detail = str(change.get("detail") or "")
    severity = "REQUIRES REVIEW"
    reason = "A monitored object changed and should be reviewed."

    if kind in {"listening_port_added"}:
        severity = "REQUIRES REVIEW"
        reason = "A new listening port appeared. It may be a legitimate service or unexpected exposure."
    elif kind in {"listening_port_removed"}:
        severity = "LIKELY APPROPRIATE"
        reason = "A listening port closed. Confirm the service was intended to stop; services were not restarted by this check."
    elif kind == "firewall_disabled":
        severity = "CRITICAL"
        reason = "The host firewall appears disabled. Entry security (Layer 1) is weakened."
    elif kind == "ssh_password_auth_enabled":
        severity = "CRITICAL"
        reason = "SSH password authentication is enabled. Brute-force risk is high compared with key-only access."
    elif kind == "ssh_root_login":
        severity = "CRITICAL"
        reason = "Root SSH login is permitted. This expands the blast radius of a stolen credential."
    elif kind == "sudo_unrestricted":
        severity = "CRITICAL"
        reason = "A sudoers rule grants unrestricted NOPASSWD ALL. This application never installs that rule."
    elif kind == "uid0_user_added":
        severity = "CRITICAL"
        reason = "A new UID 0 account was detected. Extra root users are rarely legitimate."
    elif kind == "user_added":
        severity = "REQUIRES REVIEW"
        reason = "A new login-capable user was added. Confirm this was an administrator action."
    elif kind == "user_removed":
        severity = "REQUIRES REVIEW"
        reason = "A user account disappeared. Confirm this was intended."
    elif kind == "authorized_key_added":
        severity = "SUSPICIOUS"
        reason = "A new SSH authorized key fingerprint appeared. Confirm the operator added it."
    elif kind == "service_inactive":
        name = str(change.get("service") or detail)
        if name in {"nginx", "mariadb", "mysql", "php-fpm", "ssh", "sshd"}:
            severity = "CRITICAL"
            reason = f"Production service {name} is not active. This check did not stop it."
        else:
            severity = "REQUIRES REVIEW"
            reason = f"Service {name} is inactive."
    elif kind == "permission_changed":
        if _is_config_path(path):
            severity = "SUSPICIOUS"
            reason = "Permissions changed on a configuration path. World-writable configs are especially dangerous."
        else:
            severity = "REQUIRES REVIEW"
            reason = "File mode changed. This may be an administrator chmod or an intrusion."
    elif kind == "ownership_changed":
        severity = "REQUIRES REVIEW"
        reason = "Ownership changed. Confirm the chown was performed by an administrator."
    elif kind == "type_mismatch":
        severity = "SUSPICIOUS"
        reason = "File contents do not match the expected type/signature (for example an executable disguised as an image or document)."
    elif kind == "executable_introduced":
        if path.lower().endswith(_SCRIPT_SUFFIXES) or "/cgi-bin/" in path:
            severity = "SUSPICIOUS"
            reason = "A new executable or script appeared under a web or config tree."
        else:
            severity = "REQUIRES REVIEW"
            reason = "A new executable bit or script was introduced."
    elif kind == "web_shell_hint":
        severity = "CRITICAL"
        reason = "The filename or content hint matches known web-shell patterns."
    elif kind == "deleted":
        if _path_is_cache(path):
            severity = "EXPECTED/APPROPRIATE"
            reason = "Cache, session, or log objects are expected to disappear during normal operation."
        elif _is_config_path(path):
            severity = "SUSPICIOUS"
            reason = "A configuration file was deleted."
        else:
            severity = "REQUIRES REVIEW"
            reason = "A monitored file was deleted. This is not automatically treated as an attack."
    elif kind == "created":
        if any(hint in path.lower() for hint in _WEB_SHELL_HINTS):
            severity = "CRITICAL"
            reason = "A newly created name matches a known malicious script pattern."
        elif _path_is_cache(path):
            severity = "EXPECTED/APPROPRIATE"
            reason = "New cache, session, upload, or log files are normal for OJS, PHP, and Nginx."
        elif path.lower().endswith(_EXPECTED_WEB_SUFFIXES) and not _is_config_path(path):
            severity = "LIKELY APPROPRIATE"
            reason = "A new content file appeared with a common website type. Review if unexpected."
        else:
            severity = "REQUIRES REVIEW"
            reason = "A new file or directory appeared in a monitored tree."
    elif kind == "modified":
        if _path_is_cache(path):
            severity = "EXPECTED/APPROPRIATE"
            reason = "Timestamp or content changes in cache/log/upload areas are routine."
        elif path.startswith("/etc/letsencrypt/"):
            severity = "EXPECTED/APPROPRIATE"
            reason = "Let's Encrypt certificate renewal commonly rewrites files under /etc/letsencrypt."
        elif _is_config_path(path):
            severity = "REQUIRES REVIEW"
            reason = "A configuration file changed. Nginx/PHP/SSH/sudo edits can be legitimate administrator work."
        else:
            severity = "LIKELY APPROPRIATE"
            reason = "File content or metadata changed. Applications and administrators do this during updates."
    elif kind == "renamed":
        severity = "LIKELY APPROPRIATE"
        reason = "Same inode appeared at a new path (move/rename). Confirm it was an administrator or application action."
    elif kind == "hash_changed":
        if _is_config_path(path):
            severity = "REQUIRES REVIEW"
            reason = "The cryptographic hash of a configuration file changed."
        elif _path_is_cache(path):
            severity = "EXPECTED/APPROPRIATE"
            reason = "Hash changes in cache/upload trees are expected."
        else:
            severity = "LIKELY APPROPRIATE"
            reason = "File bytes changed. Package updates, OJS, and editors do this without being malicious."

    result = dict(change)
    result["severity"] = severity
    result["reason"] = reason
    result["layer"] = layer
    if previous:
        result["previous"] = previous.get("id")
    return result


def overall_assessment(findings: list[dict[str, Any]]) -> str:
    ranks = {name: index for index, name in enumerate(SEVERITIES)}
    worst = 0
    for item in findings:
        worst = max(worst, ranks.get(str(item.get("severity")), 0))
    return SEVERITIES[worst] if findings else "EXPECTED/APPROPRIATE"


def layer_status(findings: list[dict[str, Any]], layer: str) -> str:
    subset = [item for item in findings if str(item.get("layer")) == str(layer)]
    return overall_assessment(subset)
