from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import ScenarioError

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from testgram.client import TestgramClient


@dataclass(slots=True)
class SendAction:
    text: str
    times: int
    mode: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SendAction:
        if "text" not in payload:
            raise ScenarioError("send.text is required")

        times = int(payload.get("times", 1))
        if times < 1:
            raise ScenarioError("send.times must be at least 1")

        mode = str(payload.get("mode", "sequential"))
        if mode not in {"sequential", "concurrent"}:
            raise ScenarioError("send.mode must be 'sequential' or 'concurrent'")

        return cls(
            text=str(payload["text"]),
            times=times,
            mode=mode,
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        if self.mode == "concurrent":
            await asyncio.gather(
                *(client.send_message(session, self.text) for _ in range(self.times))
            )
            return

        for _ in range(self.times):
            await client.send_message(session, self.text)

    def describe(self) -> str:
        if self.times == 1:
            return self.text
        return f"{self.text} ({self.times} times, {self.mode})"
