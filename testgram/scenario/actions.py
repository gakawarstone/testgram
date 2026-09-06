from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import ScenarioError
from .expectations import MessageMatcher

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
                await client.wait_for_update_consumed(session, update_id, self.timeout)

    def describe(self) -> str:
        if self.times == 1:
            return self.text
        return f"{self.text} ({self.times} times, {self.mode})"


@dataclass(slots=True)
class ClickAction:
    callback_data: str | None
    callback_data_regex: str | None
    button_text: str | None
    message: MessageMatcher | None
    message_id: int | None
    wait_consumed: bool
    timeout: float

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], default_timeout: float = 5.0
    ) -> ClickAction:
        callback_data = payload.get("callback_data", payload.get("data"))
        callback_data_regex = payload.get(
            "callback_data_regex", payload.get("data_regex")
        )
        button_text = payload.get("button_text")
        selectors = [callback_data, callback_data_regex, button_text]
        if sum(selector is not None for selector in selectors) != 1:
            raise ScenarioError(
                "click requires exactly one of callback_data, "
                "callback_data_regex, or button_text"
            )
        if callback_data_regex is not None:
            try:
                re.compile(str(callback_data_regex))
            except re.error as error:
                raise ScenarioError(
                    f"click.callback_data_regex is invalid: {error}"
                ) from error
        raw_message = payload.get("message")
        if raw_message is not None and not isinstance(raw_message, dict):
            raise ScenarioError("click.message must be a mapping")
        message_id = payload.get("message_id")
        return cls(
            callback_data=str(callback_data) if callback_data is not None else None,
            callback_data_regex=(
                str(callback_data_regex) if callback_data_regex is not None else None
            ),
            button_text=str(button_text) if button_text is not None else None,
            message=(
                MessageMatcher.from_payload(raw_message)
                if raw_message is not None
                else None
            ),
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
                callback_data_regex=self.callback_data_regex,
                button_text=self.button_text,
                message_matcher=self.message,
                wait_consumed=self.wait_consumed,
                timeout=self.timeout,
            )
        except ValueError as error:
            raise ScenarioError(str(error)) from error

    def describe(self) -> str:
        if self.callback_data is not None:
            selector = f"callback_data={self.callback_data!r}"
        elif self.callback_data_regex is not None:
            selector = f"callback_data_regex={self.callback_data_regex!r}"
        else:
            selector = f"button_text={self.button_text!r}"
        if self.message is not None:
            selector += f" in message matching ({self.message.describe()})"
        suffix = f" in message {self.message_id}" if self.message_id is not None else ""
        return selector + suffix
