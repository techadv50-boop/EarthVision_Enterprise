from __future__ import annotations

import json
from pathlib import Path

from app.config.schema import AgentConfig


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> AgentConfig:
        if not self.path.is_file():
            return AgentConfig()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return AgentConfig()
        if not isinstance(data, dict):
            return AgentConfig()
        return AgentConfig.from_dict(data)

    def save(self, config: AgentConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = config.to_dict()
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        tmp.replace(self.path)
