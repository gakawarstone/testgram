from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BotApiFailure:
    method: str
    error_code: int
    description: str

    @classmethod
    def from_payload(cls, payload: Any) -> BotApiFailure:
        if not isinstance(payload, dict):
            raise ValueError("fail_next must be a mapping")
        for field in payload:
            if field not in {"method", "error_code", "description"}:
                raise ValueError(f"fail_next has an unknown field {field!r}")

        method = payload.get("method")
        if not isinstance(method, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9]*", method
        ):
            raise ValueError("fail_next.method must be a Bot API method name")
        error_code = payload.get("error_code")
        if not isinstance(error_code, int) or not 400 <= error_code <= 599:
            raise ValueError("fail_next.error_code must be an integer from 400 to 599")
        description = payload.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("fail_next.description must be a non-empty string")
        return cls(method=method, error_code=error_code, description=description)
