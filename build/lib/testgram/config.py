from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_NAMES = ("testgram.yaml", "testgram.yml")


@dataclass(slots=True)
class BotConfig:
    command: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectConfig:
    path: Path | None = None
    bot: BotConfig = field(default_factory=BotConfig)

    @classmethod
    def from_file(cls, path: Path) -> ProjectConfig:
        with path.open(encoding="utf-8") as config_file:
            payload = yaml.safe_load(config_file) or {}

        if not isinstance(payload, dict):
            raise ConfigError(f"{path}: expected a YAML mapping")

        bot_payload = payload.get("bot") or {}
        if not isinstance(bot_payload, dict):
            raise ConfigError(f"{path}: bot must be a mapping")

        env_payload = bot_payload.get("env") or {}
        if not isinstance(env_payload, dict):
            raise ConfigError(f"{path}: bot.env must be a mapping")

        return cls(
            path=path,
            bot=BotConfig(
                command=optional_str(bot_payload.get("command")),
                env={str(key): str(value) for key, value in env_payload.items()},
            ),
        )


class ConfigError(Exception):
    pass


def find_config(start: Path) -> Path | None:
    directory = start.resolve()
    if directory.is_file():
        directory = directory.parent

    for candidate_dir in (directory, *directory.parents):
        for config_name in CONFIG_NAMES:
            candidate = candidate_dir / config_name
            if candidate.exists():
                return candidate

    return None


def load_project_config(path: Path | None, start: Path) -> ProjectConfig:
    if path is not None:
        return ProjectConfig.from_file(path)

    discovered = find_config(start)
    if discovered is None:
        return ProjectConfig()

    return ProjectConfig.from_file(discovered)


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
