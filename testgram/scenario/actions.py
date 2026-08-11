from __future__ import annotations

import asyncio
import math
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
    wait_consumed: bool
    timeout: float

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], default_timeout: float = 5.0
    ) -> SendAction:
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
            wait_consumed=bool(payload.get("wait_consumed", True)),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        if self.mode == "concurrent":
            update_ids = await asyncio.gather(
                *(client.send_message(session, self.text) for _ in range(self.times))
            )
            if self.wait_consumed:
                await asyncio.gather(
                    *(
                        client.wait_for_update_consumed(
                            session, update_id, self.timeout
                        )
                        for update_id in update_ids
                    )
                )
            return

        for _ in range(self.times):
            update_id = await client.send_message(session, self.text)
            if self.wait_consumed:
                await client.wait_for_update_consumed(
                    session, update_id, self.timeout
                )

    def describe(self) -> str:
        if self.times == 1:
            return self.text
        return f"{self.text} ({self.times} times, {self.mode})"


@dataclass(slots=True)
class ClickAction:
    callback_data: str
    message_id: int | None
    wait_consumed: bool
    timeout: float

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], default_timeout: float = 5.0
    ) -> ClickAction:
        callback_data = payload.get("callback_data", payload.get("data"))
        if callback_data is None:
            raise ScenarioError("click.callback_data is required")
        message_id = payload.get("message_id")
        return cls(
            callback_data=str(callback_data),
            message_id=int(message_id) if message_id is not None else None,
            wait_consumed=bool(payload.get("wait_consumed", True)),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> int:
        try:
            return await client.click(
                session,
                callback_data=self.callback_data,
                message_id=self.message_id,
                wait_consumed=self.wait_consumed,
                timeout=self.timeout,
            )
        except ValueError as error:
            raise ScenarioError(str(error)) from error

    def describe(self) -> str:
        suffix = f" in message {self.message_id}" if self.message_id is not None else ""
        return f"callback_data={self.callback_data!r}{suffix}"


@dataclass(slots=True)
class AdvanceTimeAction:
    seconds: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AdvanceTimeAction:
        if "seconds" not in payload:
            raise ScenarioError("advance_time.seconds is required")
        seconds = float(payload["seconds"])
        if not math.isfinite(seconds) or seconds < 0:
            raise ScenarioError("advance_time.seconds must be non-negative")
        return cls(seconds=seconds)

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        await client.advance_time(session, self.seconds)

    def describe(self) -> str:
        return f"{self.seconds:g} second(s)"
