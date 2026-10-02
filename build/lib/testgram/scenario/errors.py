from __future__ import annotations

from pathlib import Path
from typing import Any


class ScenarioError(Exception):
    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        line: int | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.line = line
        super().__init__(message)

    def __str__(self) -> str:
        if self.path is None:
            return self.message
        if self.line is None:
            return f"{self.path}: {self.message}"
        return f"{self.path}:{self.line}: {self.message}"


def require_mapping(
    value: Any,
    name: str,
    path: Path | None,
    line: int | None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{name} must be a mapping", path=path, line=line)
    return value
