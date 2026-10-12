"""Load the relay config from YAML. Secrets come from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from relay.paths import PathError, check_id

Protocol = Literal["sftp", "ftps"]
HostKeyPolicy = Literal["reject", "accept-new"]
DeliverTo = tuple[str, ...] | Literal["all"]


class ConfigError(ValueError):
    """The config file is missing a field or contradicts itself."""


@dataclass(frozen=True)
class Endpoint:
    id: str
    protocol: Protocol
    host: str
    port: int
    username: str
    remote_dir: str
    password: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = None
    known_hosts_path: str | None = None
    host_key_policy: HostKeyPolicy = "reject"

    def __repr__(self) -> str:
        return (
            f"Endpoint(id={self.id!r}, protocol={self.protocol!r}, "
            f"host={self.host!r}, port={self.port!r}, username={self.username!r})"
        )


@dataclass(frozen=True)
class Source:
    endpoint: Endpoint
    deliver_to: DeliverTo


@dataclass(frozen=True)
class Settings:
    poll_interval_seconds: int
    local_ttl_hours: float
    stability_seconds: float
    staging_dir: Path
    database_path: Path
    sources: tuple[Source, ...]
    destinations: tuple[Endpoint, ...]

    def destinations_for(self, source: Source) -> tuple[Endpoint, ...]:
        if source.deliver_to == "all":
            return self.destinations
        by_id = {item.id: item for item in self.destinations}
        return tuple(by_id[item_id] for item_id in source.deliver_to)


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")

    poll_interval = _int_at_least(raw, "poll_interval_seconds", 1)
    ttl_hours = _positive_number(raw, "local_ttl_hours", minimum=0, allow_zero=False)
    if "stability_seconds" in raw:
        stability = _positive_number(raw, "stability_seconds", minimum=0, allow_zero=True)
    else:
        stability = float(poll_interval)

    staging_dir = Path(_required_str(raw, "staging_dir"))
    database_path = Path(_required_str(raw, "database_path"))

    sources_raw = raw.get("sources")
    destinations_raw = raw.get("destinations")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError("sources must be a non-empty list")
    if not isinstance(destinations_raw, list) or not destinations_raw:
        raise ConfigError("destinations must be a non-empty list")

    destinations = tuple(_endpoint(item, "destinations") for item in destinations_raw)
    destination_ids = _unique_ids(destinations, "destination")
    sources = tuple(
        _source(item, destination_ids) for item in sources_raw
    )
    _unique_ids(tuple(source.endpoint for source in sources), "source")

    taken = {item.id for item in destinations}
    for source in sources:
        if source.endpoint.id in taken:
            raise ConfigError(
                f"id {source.endpoint.id!r} is used by both a source and a destination"
            )

    return Settings(
        poll_interval_seconds=int(poll_interval),
        local_ttl_hours=float(ttl_hours),
        stability_seconds=float(stability),
        staging_dir=staging_dir,
        database_path=database_path,
        sources=sources,
        destinations=destinations,
    )


def _source(block: Any, destination_ids: set[str]) -> Source:
    endpoint = _endpoint(block, "sources")
    if "deliver_to" not in block:
        raise ConfigError(f"source {endpoint.id} is missing deliver_to")
    deliver_to = _deliver_to(block["deliver_to"], endpoint.id, destination_ids)
    return Source(endpoint=endpoint, deliver_to=deliver_to)


def _deliver_to(value: Any, source_id: str, destination_ids: set[str]) -> DeliverTo:
    if value == "all":
        return "all"
    if isinstance(value, str):
        names = [value]
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        names = list(value)
    else:
        raise ConfigError(
            f"source {source_id} deliver_to must be 'all', a destination id, or a list of ids"
        )
    unknown = [name for name in names if name not in destination_ids]
    if unknown:
        raise ConfigError(
            f"source {source_id} deliver_to names unknown destinations: {', '.join(unknown)}"
        )
    if len(set(names)) != len(names):
        raise ConfigError(f"source {source_id} deliver_to repeats a destination")
    return tuple(names)


def _endpoint(block: Any, label: str) -> Endpoint:
    if not isinstance(block, dict):
        raise ConfigError(f"each {label} entry must be a mapping")
    endpoint_id = _checked_id(_required_str(block, "id"))
    protocol = _required_str(block, "protocol")
    if protocol not in ("sftp", "ftps"):
        raise ConfigError(
            f"{endpoint_id} protocol must be sftp or ftps (plain ftp is not supported)"
        )
    password = _secret(block, "password", "password_env")
    passphrase = _secret(block, "private_key_passphrase", "private_key_passphrase_env")
    private_key_path = block.get("private_key_path")
    if private_key_path is not None and not isinstance(private_key_path, str):
        raise ConfigError(f"{endpoint_id} private_key_path must be a string")
    if protocol == "ftps":
        if not password:
            raise ConfigError(f"{endpoint_id} ftps requires a password")
        if private_key_path:
            raise ConfigError(f"{endpoint_id} ftps does not use a private key")
    elif not password and not private_key_path:
        raise ConfigError(f"{endpoint_id} sftp requires a password or a private key")

    remote_dir = _required_str(block, "remote_dir").strip()
    if not remote_dir or remote_dir == "/":
        raise ConfigError(f"{endpoint_id} remote_dir must be a directory, not {remote_dir!r}")

    return Endpoint(
        id=endpoint_id,
        protocol=protocol,  # type: ignore[arg-type]
        host=_required_str(block, "host"),
        port=_port(block, endpoint_id),
        username=_required_str(block, "username"),
        remote_dir=remote_dir,
        password=password,
        private_key_path=private_key_path,
        private_key_passphrase=passphrase,
        known_hosts_path=_optional_str(block, "known_hosts_path"),
        host_key_policy=_host_key_policy(block, endpoint_id),
    )


def _secret(block: dict[str, Any], field: str, env_field: str) -> str | None:
    literal = block.get(field)
    env_name = block.get(env_field)
    if literal is not None and not isinstance(literal, str):
        raise ConfigError(f"{field} must be a string")
    if env_name is not None and not isinstance(env_name, str):
        raise ConfigError(f"{env_field} must be a string")
    if literal and env_name:
        raise ConfigError(f"set only one of {field} and {env_field}")
    if env_name:
        try:
            return os.environ[env_name]
        except KeyError as exc:
            raise ConfigError(f"environment variable {env_name} is not set") from exc
    return literal or None


def _host_key_policy(block: dict[str, Any], endpoint_id: str) -> HostKeyPolicy:
    value = block.get("host_key_policy", "reject")
    if value not in ("reject", "accept-new"):
        raise ConfigError(
            f"{endpoint_id} host_key_policy must be 'reject' or 'accept-new'"
        )
    return value  # type: ignore[return-value]


def _port(block: dict[str, Any], endpoint_id: str) -> int:
    if "port" not in block:
        raise ConfigError(f"{endpoint_id} is missing port")
    value = block["port"]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ConfigError(f"{endpoint_id} port must be an integer from 1 to 65535")
    return value


def _unique_ids(endpoints: tuple[Endpoint, ...], label: str) -> set[str]:
    seen: set[str] = set()
    for endpoint in endpoints:
        if endpoint.id in seen:
            raise ConfigError(f"duplicate {label} id {endpoint.id!r}")
        seen.add(endpoint.id)
    return seen


def _required_str(block: dict[str, Any], field: str) -> str:
    value = block.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_str(block: dict[str, Any], field: str) -> str | None:
    value = block.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _checked_id(value: str) -> str:
    try:
        return check_id(value)
    except PathError as exc:
        raise ConfigError(str(exc)) from exc


def _int_at_least(block: dict[str, Any], field: str, minimum: int) -> int:
    if field not in block:
        raise ConfigError(f"{field} is required")
    value = block[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{field} must be an integer >= {minimum}")
    return value


def _positive_number(
    block: dict[str, Any],
    field: str,
    *,
    minimum: float,
    allow_zero: bool = False,
) -> float:
    if field not in block:
        raise ConfigError(f"{field} is required")
    value = block[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} must be a number")
    if allow_zero:
        if value < minimum:
            raise ConfigError(f"{field} must be >= {minimum}")
    elif value <= minimum:
        raise ConfigError(f"{field} must be > {minimum}")
    return float(value)
