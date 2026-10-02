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
    message: dict[str, Any]
    times: int
    mode: str
    wait_consumed: bool
    timeout: float

    @property
    def text(self) -> str | None:
        value = self.message.get("text")
        return None if value is None else str(value)

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], default_timeout: float = 5.0
    ) -> SendAction:
        content_types = [
            key for key in ("text", "document", "photo", "audio") if key in payload
        ]
        if not content_types:
            raise ScenarioError(
                "send requires one of text, document, photo, or audio"
            )
        if len(content_types) > 1:
            raise ScenarioError("send accepts only one message content type")

        times = int(payload.get("times", 1))
        if times < 1:
            raise ScenarioError("send.times must be at least 1")

        mode = str(payload.get("mode", "sequential"))
        if mode not in {"sequential", "concurrent"}:
            raise ScenarioError("send.mode must be 'sequential' or 'concurrent'")

        return cls(
            message={
                key: value
                for key, value in payload.items()
                if key not in {"times", "mode", "wait_consumed", "timeout"}
            },
            times=times,
            mode=mode,
            wait_consumed=bool(payload.get("wait_consumed", True)),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        if self.mode == "concurrent":
            update_ids = await asyncio.gather(
                *(client.send(session, self.message) for _ in range(self.times))
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
            update_id = await client.send(session, self.message)
            if self.wait_consumed:
                await client.wait_for_update_consumed(session, update_id, self.timeout)

    def describe(self) -> str:
        content_type = next(
            key for key in ("text", "document", "photo", "audio") if key in self.message
        )
        content = self.message[content_type]
        description = str(content) if content_type == "text" else f"[{content_type}]"
        if self.times == 1:
            return description
        return f"{description} ({self.times} times, {self.mode})"


@dataclass(slots=True)
class ClickAction:
    callback_data: str | None
    callback_data_regex: str | None
    button_text: str | None
    message: MessageMatcher | None
    message_id: int | None
    wait_consumed: bool
    timeout: float
    user: dict[str, Any] | None = None

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
        user = _identity(payload)
        if user is not None and not isinstance(user, dict):
            raise ScenarioError("click.user must be a mapping")
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
            user=user,
            wait_consumed=bool(payload.get("wait_consumed", True)),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> int:
        try:
            return await client.click(
                session,
                callback_data=self.callback_data,
                message_id=self.message_id,
                user=self.user,
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


@dataclass(slots=True)
class InlineQueryAction:
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> InlineQueryAction:
        if "query" not in payload:
            raise ScenarioError("inline_query.query is required")
        user = _identity(payload)
        if user is not None and not isinstance(user, dict):
            raise ScenarioError("inline_query.user must be a mapping")
        location = payload.get("location")
        if location is not None and not isinstance(location, dict):
            raise ScenarioError("inline_query.location must be a mapping")
        return cls(payload=dict(payload))

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        await client.send_inline_query(session, self.payload)

    def describe(self) -> str:
        return str(self.payload["query"])


@dataclass(slots=True)
class UpdateAction:
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> UpdateAction:
        if not payload:
            raise ScenarioError("update must not be empty")
        return cls(payload=dict(payload))

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        await client.send_raw_update(session, self.payload)

    def describe(self) -> str:
        return ", ".join(self.payload)


def _identity(payload: dict[str, Any]) -> Any:
    return next(
        (
            payload[key]
            for key in ("user", "from_user", "from", "identity")
            if key in payload
        ),
        None,
    )
