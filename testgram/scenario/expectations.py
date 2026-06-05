from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import ScenarioError

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from testgram.client import TestgramClient



@dataclass(slots=True)
class Expectation:
    method: str | None
    text: str | None
    text_contains: str | None
    timeout: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any], default_timeout: float) -> Expectation:
        return cls(
            method=optional_str(payload.get("method")),
            text=optional_str(payload.get("text")),
            text_contains=optional_str(payload.get("text_contains")),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    def find_match(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        for event in events:
            if self.matches(event):
                return event
        return None

    def matches(self, event: dict[str, Any]) -> bool:
        payload = event.get("payload", {})
        request_payload = payload.get("payload", {})

        if self.method is not None and payload.get("method") != self.method:
            return False

        text = request_payload.get("text") or request_payload.get("caption") or ""
        if self.text is not None and text != self.text:
            return False
        if self.text_contains is not None and self.text_contains not in text:
            return False

        return True

    def describe(self) -> str:
        parts = []
        if self.method is not None:
            parts.append(f"method={self.method}")
        if self.text is not None:
            parts.append(f"text={self.text!r}")
        if self.text_contains is not None:
            parts.append(f"text_contains={self.text_contains!r}")
        return ", ".join(parts) or "any bot message"


@dataclass(slots=True)
class ChatExpectation:
    bot_messages: ChatBotMessagesExpectation | None
    no_errors: bool
    timeout: float

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        default_timeout: float,
    ) -> ChatExpectation:
        bot_messages = None
        if "bot_messages" in payload:
            if not isinstance(payload["bot_messages"], dict):
                raise ScenarioError("expect_chat.bot_messages must be a mapping")
            bot_messages = ChatBotMessagesExpectation.from_payload(payload["bot_messages"])

        return cls(
            bot_messages=bot_messages,
            no_errors=bool(payload.get("no_errors", False)),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    async def wait_for_match(
        self,
        client: TestgramClient,
        session: ClientSession,
        scenario_start_events: int,
    ) -> list[dict[str, Any]]:
        deadline = asyncio.get_running_loop().time() + self.timeout
        events: list[dict[str, Any]] = []

        while asyncio.get_running_loop().time() < deadline:
            events = (await client.get_events(session))[scenario_start_events:]
            if self.matches(client=client, events=events):
                return events
            await asyncio.sleep(0.2)

        events = (await client.get_events(session))[scenario_start_events:]
        if self.matches(client=client, events=events):
            return events

        raise ScenarioError(f"expect_chat failed: {self.failure_reason(client, events)}")

    def matches(self, client: TestgramClient, events: list[dict[str, Any]]) -> bool:
        if self.no_errors and has_error_event(events):
            return False

        if self.bot_messages is not None and not self.bot_messages.matches(
            client=client,
            events=events,
        ):
            return False

        return True

    def failure_reason(self, client: TestgramClient, events: list[dict[str, Any]]) -> str:
        reasons = []
        if self.no_errors and has_error_event(events):
            reasons.append("found error event")
        if self.bot_messages is not None:
            reason = self.bot_messages.failure_reason(client=client, events=events)
            if reason is not None:
                reasons.append(reason)
        return ", ".join(reasons) or "chat did not match"

    def describe(self, client: TestgramClient, events: list[dict[str, Any]]) -> str:
        if self.bot_messages is None:
            bot_count = sum(
                1 for event in events if event.get("type") == "bot_api_request"
            )
        else:
            bot_count = len(
                self.bot_messages.matching_messages(
                    client=client,
                    events=events,
                )
            )
        return f"{bot_count} bot API request(s) matched"


@dataclass(slots=True)
class ChatBotMessagesExpectation:
    count: int | None
    method: str | None
    text: str | None
    text_contains: str | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ChatBotMessagesExpectation:
        count = payload.get("count")
        return cls(
            count=int(count) if count is not None else None,
            method=optional_str(payload.get("method")),
            text=optional_str(payload.get("text")),
            text_contains=optional_str(payload.get("text_contains")),
        )

    def matches(self, client: TestgramClient, events: list[dict[str, Any]]) -> bool:
        messages = self.matching_messages(client=client, events=events)
        if self.count is not None and len(messages) != self.count:
            return False
        return True

    def failure_reason(
        self,
        client: TestgramClient,
        events: list[dict[str, Any]],
    ) -> str | None:
        messages = self.matching_messages(client=client, events=events)
        if self.count is not None and len(messages) != self.count:
            return f"expected {self.count} bot message(s), found {len(messages)}"
        return None

    def matching_messages(
        self,
        client: TestgramClient,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in events
            if client.is_bot_reply(event) and self.matches_filters(event)
        ]

    def matches_filters(self, event: dict[str, Any]) -> bool:
        payload = event.get("payload", {})
        request_payload = payload.get("payload", {})

        if self.method is not None and payload.get("method") != self.method:
            return False

        text = request_payload.get("text") or request_payload.get("caption") or ""
        if self.text is not None and text != self.text:
            return False
        if self.text_contains is not None and self.text_contains not in text:
            return False

        return True


def has_error_event(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if "error" in str(event.get("type", "")).lower():
            return True

        payload = event.get("payload", {})
        response = payload.get("response", {})
        if isinstance(response, dict) and response.get("ok") is False:
            return True

    return False


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
