from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, log_file: Path | None = None) -> None:
        self._log_file = log_file

    async def write(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "time": datetime.now(tz=UTC).isoformat(),
            "type": event_type,
            "payload": self._json_safe(payload),
        }
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        print(line, flush=True)

        if self._log_file is not None:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with self._log_file.open("a", encoding="utf-8") as log:
                log.write(f"{line}\n")

        return event

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._json_safe(item) for item in value]
        if isinstance(value, str | int | float | bool) or value is None:
            return value
        return repr(value)
