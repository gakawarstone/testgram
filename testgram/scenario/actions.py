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
    message: dict[str, Any]
    times: int
    mode: str

    @property
    def text(self) -> str | None:
        value = self.message.get("text")
        return None if value is None else str(value)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SendAction:
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
                if key not in {"times", "mode"}
            },
            times=times,
            mode=mode,
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        if self.mode == "concurrent":
            await asyncio.gather(
                *(client.send(session, self.message) for _ in range(self.times))
            )
            return

        for _ in range(self.times):
            await client.send(session, self.message)

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
    callback_data: str
    message_id: int | None
    user: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ClickAction:
        callback_data = payload.get("callback_data", payload.get("data"))
        if callback_data is None:
            raise ScenarioError("click.callback_data is required")
        message_id = payload.get("message_id")
        user = _identity(payload)
        if user is not None and not isinstance(user, dict):
            raise ScenarioError("click.user must be a mapping")
        return cls(
            callback_data=str(callback_data),
            message_id=int(message_id) if message_id is not None else None,
            user=user,
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> int:
        try:
            return await client.click(
                session,
                callback_data=self.callback_data,
                message_id=self.message_id,
                user=self.user,
            )
        except ValueError as error:
            raise ScenarioError(str(error)) from error

    def describe(self) -> str:
        suffix = f" in message {self.message_id}" if self.message_id is not None else ""
        return f"callback_data={self.callback_data!r}{suffix}"


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
