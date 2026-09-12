from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ScenarioError
from .loader import SourceLineLoader, source_line


@dataclass(slots=True)
class Scenario:
    name: str
    steps: list[ScenarioStep]
    timeout: float
    path: Path

    @classmethod
    def from_file(cls, path: Path, default_timeout: float) -> Scenario:
        with path.open(encoding="utf-8") as scenario_file:
            if path.suffix.lower() in {".yaml", ".yml"}:
                payload = yaml.load(scenario_file, Loader=SourceLineLoader)
            else:
                payload = json.load(scenario_file)

        if not isinstance(payload, dict):
            raise ScenarioError("expected a scenario mapping", path=path)

        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            raise ScenarioError("steps must be a list", path=path)

        steps = []
        for index, step in enumerate(raw_steps, start=1):
            if not isinstance(step, dict):
                raise ScenarioError(
                    f"{index}. step must be a mapping",
                    path=path,
                    line=source_line(step),
                )
            steps.append(ScenarioStep(payload=dict(step), line=source_line(step)))

        return cls(
            name=str(payload.get("name", path.stem)),
            steps=steps,
            timeout=float(payload.get("timeout", default_timeout)),
            path=path,
        )


@dataclass(slots=True)
class ScenarioStep:
    payload: dict[str, Any]
    line: int | None
