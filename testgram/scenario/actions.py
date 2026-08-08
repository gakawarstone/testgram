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


@dataclass(slots=True)
class ClickAction:
    callback_data: str
    message_id: int | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ClickAction:
        callback_data = payload.get("callback_data", payload.get("data"))
        if callback_data is None:
            raise ScenarioError("click.callback_data is required")
        message_id = payload.get("message_id")
        return cls(
            callback_data=str(callback_data),
            message_id=int(message_id) if message_id is not None else None,
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> int:
        try:
            return await client.click(
                session,
                callback_data=self.callback_data,
                message_id=self.message_id,
            )
        except ValueError as error:
            raise ScenarioError(str(error)) from error

    def describe(self) -> str:
        suffix = f" in message {self.message_id}" if self.message_id is not None else ""
        return f"callback_data={self.callback_data!r}{suffix}"
