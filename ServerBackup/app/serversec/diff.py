"""Diff two security snapshots without loading website file contents."""

from __future__ import annotations

from typing import Any


def _index_files(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = snapshot.get("files") or []
    return {str(item.get("path")): item for item in files if item.get("path")}


def compare_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    prev_files = _index_files(previous)
    curr_files = _index_files(current)

    prev_inodes = {
        (item.get("dev"), item.get("ino")): path
        for path, item in prev_files.items()
        if item.get("ino")
    }
    used_old: set[str] = set()
    used_new: set[str] = set()

    for path, item in curr_files.items():
        key = (item.get("dev"), item.get("ino"))
        old_path = prev_inodes.get(key)
        if old_path and old_path != path and old_path in prev_files:
            changes.append(
                {
                    "kind": "renamed",
                    "layer": "3",
                    "path": path,
                    "from": old_path,
                    "detail": f"{old_path} -> {path}",
                }
            )
            used_old.add(old_path)
            used_new.add(path)

    for path, old in prev_files.items():
        if path in used_old:
            continue
        new = curr_files.get(path)
        if not new:
            changes.append({"kind": "deleted", "layer": "3", "path": path, "detail": "missing in current snapshot"})
            continue
        used_new.add(path)
        if old.get("mode") != new.get("mode"):
            changes.append(
                {
                    "kind": "permission_changed",
                    "layer": "3",
                    "path": path,
                    "detail": f"{old.get('mode')} -> {new.get('mode')}",
                }
            )
        if (old.get("uid"), old.get("gid")) != (new.get("uid"), new.get("gid")):
            changes.append(
                {
                    "kind": "ownership_changed",
                    "layer": "3",
                    "path": path,
                    "detail": f"{old.get('uid')}:{old.get('gid')} -> {new.get('uid')}:{new.get('gid')}",
                }
            )
        if old.get("type") != new.get("type") or (
            old.get("signature") and new.get("signature") and old.get("signature") != new.get("signature")
        ):
            if old.get("signature") != new.get("signature") and new.get("mismatch"):
                changes.append(
                    {
                        "kind": "type_mismatch",
                        "layer": "3",
                        "path": path,
                        "detail": new.get("mismatch"),
                    }
                )
        if old.get("sha256") and new.get("sha256") and old.get("sha256") != new.get("sha256"):
            changes.append({"kind": "hash_changed", "layer": "3", "path": path, "detail": "content hash changed"})
        elif old.get("mtime") != new.get("mtime") or old.get("size") != new.get("size"):
            changes.append({"kind": "modified", "layer": "3", "path": path, "detail": "mtime or size changed"})

    for path, item in curr_files.items():
        if path in used_new or path in prev_files:
            continue
        kind = "created"
        if item.get("mismatch"):
            kind = "type_mismatch"
        elif item.get("executable_new"):
            kind = "executable_introduced"
        changes.append({"kind": kind, "layer": "3", "path": path, "detail": item.get("detail") or "new path"})

    changes.extend(_layer1_diff(previous, current))
    changes.extend(_layer2_diff(previous, current))
    return changes


def _set_diff(old: list, new: list) -> tuple[set, set]:
    o = {jsonable(x) for x in old}
    n = {jsonable(x) for x in new}
    return n - o, o - n


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, jsonable(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(jsonable(v) for v in value)
    return value


def _layer1_diff(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    old_ports = {str(p) for p in (previous.get("layer1") or {}).get("listening_ports") or []}
    new_ports = {str(p) for p in (current.get("layer1") or {}).get("listening_ports") or []}
    for port in sorted(new_ports - old_ports):
        changes.append({"kind": "listening_port_added", "layer": "1", "path": "", "detail": port})
    for port in sorted(old_ports - new_ports):
        changes.append({"kind": "listening_port_removed", "layer": "1", "path": "", "detail": port})
    old_fw = (previous.get("layer1") or {}).get("firewall_active")
    new_fw = (current.get("layer1") or {}).get("firewall_active")
    if old_fw and new_fw is False:
        changes.append({"kind": "firewall_disabled", "layer": "1", "path": "", "detail": "firewall inactive"})
    old_ssh = (previous.get("layer1") or {}).get("sshd") or {}
    new_ssh = (current.get("layer1") or {}).get("sshd") or {}
    if str(new_ssh.get("PasswordAuthentication") or "").lower() in {"yes", "true"}:
        if str(old_ssh.get("PasswordAuthentication") or "").lower() not in {"yes", "true"}:
            changes.append({"kind": "ssh_password_auth_enabled", "layer": "1", "path": "/etc/ssh/sshd_config", "detail": "PasswordAuthentication yes"})
    if str(new_ssh.get("PermitRootLogin") or "").lower() in {"yes", "prohibit-password"}:
        if str(old_ssh.get("PermitRootLogin") or "").lower() not in {"yes", "prohibit-password"}:
            changes.append({"kind": "ssh_root_login", "layer": "1", "path": "/etc/ssh/sshd_config", "detail": str(new_ssh.get("PermitRootLogin"))})
    return changes


def _layer2_diff(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    old_users = {u.get("name") for u in (previous.get("layer2") or {}).get("users") or [] if isinstance(u, dict)}
    new_users = {u.get("name") for u in (current.get("layer2") or {}).get("users") or [] if isinstance(u, dict)}
    for name in sorted(new_users - old_users):
        uid0 = any(
            u.get("name") == name and u.get("uid") is not None and int(u.get("uid")) == 0
            for u in (current.get("layer2") or {}).get("users") or []
            if isinstance(u, dict)
        )
        kind = "uid0_user_added" if uid0 else "user_added"
        changes.append({"kind": kind, "layer": "2", "path": "", "detail": str(name)})
    for name in sorted(old_users - new_users):
        changes.append({"kind": "user_removed", "layer": "2", "path": "", "detail": str(name)})
    old_keys = set((previous.get("layer2") or {}).get("authorized_key_fps") or [])
    new_keys = set((current.get("layer2") or {}).get("authorized_key_fps") or [])
    for fp in sorted(new_keys - old_keys):
        changes.append({"kind": "authorized_key_added", "layer": "2", "path": "", "detail": str(fp)})
    if (current.get("layer2") or {}).get("sudo_unrestricted"):
        if not (previous.get("layer2") or {}).get("sudo_unrestricted"):
            changes.append({"kind": "sudo_unrestricted", "layer": "2", "path": "/etc/sudoers", "detail": "NOPASSWD: ALL"})
    old_svc = {s.get("name"): s.get("active") for s in (previous.get("layer2") or {}).get("services") or [] if isinstance(s, dict)}
    # services also live in health
    old_svc.update({s.get("name"): s.get("active") for s in (previous.get("health") or {}).get("services") or [] if isinstance(s, dict)})
    new_svc = {s.get("name"): s.get("active") for s in (current.get("health") or {}).get("services") or [] if isinstance(s, dict)}
    for name, active in new_svc.items():
        if old_svc.get(name) and not active:
            changes.append({"kind": "service_inactive", "layer": "2", "path": "", "detail": name, "service": name})
    return changes
