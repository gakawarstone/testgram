from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any

from .errors import ScenarioError

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from testgram.client import TestgramClient


MEDIA_METHODS = {
    "sendPhoto": "photo",
    "sendDocument": "document",
    "sendVideo": "video",
    "sendAudio": "audio",
    "sendVoice": "voice",
    "sendAnimation": "animation",
    "sendSticker": "sticker",
}


@dataclass(slots=True)
class MessageMatcher:
    method: str | None = None
    text: str | None = None
    text_contains: str | None = None
    reply_markup: Any = None
    callback_data: str | None = None
    media_type: str | None = None
    filename: str | None = None
    duration: float | None = None
    caption: str | None = None
    parse_mode: str | None = None
    chat_id: int | str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MessageMatcher:
        duration = payload.get("duration")
        return cls(
            method=optional_str(payload.get("method")),
            text=optional_str(payload.get("text")),
            text_contains=optional_str(payload.get("text_contains")),
            reply_markup=payload.get("reply_markup"),
            callback_data=optional_str(payload.get("callback_data")),
            media_type=optional_str(payload.get("media_type")),
            filename=optional_str(payload.get("filename")),
            duration=float(duration) if duration is not None else None,
            caption=optional_str(payload.get("caption")),
            parse_mode=optional_str(payload.get("parse_mode")),
            chat_id=payload.get("chat_id"),
        )

    def matches(self, event: dict[str, Any]) -> bool:
        payload = event.get("payload", {})
        request_payload = payload.get("payload", {})
        if not isinstance(request_payload, dict):
            return False

        if self.method is not None and payload.get("method") != self.method:
            return False

        text = request_payload.get("text") or request_payload.get("caption") or ""
        if self.text is not None and str(text) != self.text:
            return False
        if self.text_contains is not None and self.text_contains not in str(text):
            return False
        if self.caption is not None and request_payload.get("caption") != self.caption:
            return False
        if self.parse_mode is not None and request_payload.get("parse_mode") != self.parse_mode:
            return False
        if self.chat_id is not None and str(request_payload.get("chat_id")) != str(
            self.chat_id
        ):
            return False

        reply_markup = normalize_json(request_payload.get("reply_markup"))
        if self.reply_markup is not None and reply_markup != self.reply_markup:
            return False
        if self.callback_data is not None and not contains_callback_data(
            reply_markup, self.callback_data
        ):
            return False

        if self.media_type is not None and self.media_type not in event_media_types(
            payload.get("method"), request_payload
        ):
            return False
        if self.filename is not None and self.filename not in filenames(request_payload):
            return False
        if self.duration is not None and self.duration not in durations(request_payload):
            return False

        return True

    def describe(self) -> str:
        parts = []
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                parts.append(f"{field.name}={value!r}")
        return ", ".join(parts) or "any bot message"


@dataclass(slots=True)
class Expectation:
    matcher: MessageMatcher
    timeout: float
    order: int | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any], default_timeout: float) -> Expectation:
        raw_order = payload.get(
            "order", payload.get("message_order", payload.get("position"))
        )
        order = int(raw_order) if raw_order is not None else None
        if order is not None and order < 1:
            raise ScenarioError("expect.order must be at least 1")
        return cls(
            matcher=MessageMatcher.from_payload(payload),
            timeout=float(payload.get("timeout", default_timeout)),
            order=order,
        )

    async def wait_for_match(
        self,
        client: TestgramClient,
        session: ClientSession,
        seen_events: int,
    ) -> tuple[int, dict[str, Any]] | None:
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            events = await client.get_events(session)
            bot_events = [
                (index, event)
                for index, event in enumerate(events[seen_events:], start=seen_events)
                if client.is_bot_reply(event)
            ]
            match = self.find_indexed_match(bot_events)
            if match is not None:
                return match
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.2)

    def find_indexed_match(
        self, events: list[tuple[int, dict[str, Any]]]
    ) -> tuple[int, dict[str, Any]] | None:
        if self.order is not None:
            if len(events) < self.order:
                return None
            candidate = events[self.order - 1]
            return candidate if self.matcher.matches(candidate[1]) else None
        return next((item for item in events if self.matcher.matches(item[1])), None)

    def describe(self) -> str:
        description = self.matcher.describe()
        if self.order is not None:
            description += f", order={self.order}"
        return description


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
        return self.bot_messages is None or self.bot_messages.matches(client, events)

    def failure_reason(self, client: TestgramClient, events: list[dict[str, Any]]) -> str:
        reasons = []
        if self.no_errors and has_error_event(events):
            reasons.append("found error event")
        if self.bot_messages is not None:
            reason = self.bot_messages.failure_reason(client, events)
            if reason is not None:
                reasons.append(reason)
        return ", ".join(reasons) or "chat did not match"

    def describe(self, client: TestgramClient, events: list[dict[str, Any]]) -> str:
        if self.bot_messages is None:
            bot_count = sum(1 for event in events if client.is_bot_reply(event))
        else:
            bot_count = len(self.bot_messages.matching_messages(client, events))
        return f"{bot_count} bot API request(s) matched"


@dataclass(slots=True)
class ChatBotMessagesExpectation:
    count: int | None
    matcher: MessageMatcher
    ordered_messages: list[MessageMatcher]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ChatBotMessagesExpectation:
        count = payload.get("count")
        raw_messages = payload.get("messages", payload.get("order", []))
        if isinstance(payload.get("ordered"), list):
            raw_messages = payload["ordered"]
        if not isinstance(raw_messages, list):
            raise ScenarioError("expect_chat.bot_messages.messages must be a list")
        ordered_messages = []
        for message in raw_messages:
            if not isinstance(message, dict):
                raise ScenarioError(
                    "expect_chat.bot_messages.messages entries must be mappings"
                )
            ordered_messages.append(MessageMatcher.from_payload(message))
        return cls(
            count=int(count) if count is not None else None,
            matcher=MessageMatcher.from_payload(payload),
            ordered_messages=ordered_messages,
        )

    def matches(self, client: TestgramClient, events: list[dict[str, Any]]) -> bool:
        messages = self.matching_messages(client, events)
        if self.count is not None and len(messages) != self.count:
            return False
        return self._ordered_match(client, events)

    def failure_reason(
        self, client: TestgramClient, events: list[dict[str, Any]]
    ) -> str | None:
        messages = self.matching_messages(client, events)
        if self.count is not None and len(messages) != self.count:
            return f"expected {self.count} bot message(s), found {len(messages)}"
        if not self._ordered_match(client, events):
            expected = " -> ".join(item.describe() for item in self.ordered_messages)
            return f"bot messages were not found in order: {expected}"
        return None

    def matching_messages(
        self, client: TestgramClient, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in events
            if client.is_bot_reply(event) and self.matcher.matches(event)
        ]

    def _ordered_match(
        self, client: TestgramClient, events: list[dict[str, Any]]
    ) -> bool:
        if not self.ordered_messages:
            return True
        remaining = iter(self.ordered_messages)
        wanted = next(remaining, None)
        for event in events:
            if client.is_bot_reply(event) and wanted is not None and wanted.matches(event):
                wanted = next(remaining, None)
        return wanted is None


def event_media_types(method: Any, payload: dict[str, Any]) -> set[str]:
    media_types = set()
    if method in MEDIA_METHODS:
        media_types.add(MEDIA_METHODS[method])
    media = normalize_json(payload.get("media"))
    if isinstance(media, list):
        for item in media:
            if isinstance(item, dict) and item.get("type") is not None:
                media_types.add(str(item["type"]))
    elif isinstance(media, dict) and media.get("type") is not None:
        media_types.add(str(media["type"]))
    return media_types


def filenames(value: Any) -> set[str]:
    found = set()
    value = normalize_json(value)
    if isinstance(value, dict):
        if isinstance(value.get("filename"), str):
            found.add(value["filename"])
        for item in value.values():
            found.update(filenames(item))
    elif isinstance(value, list):
        for item in value:
            found.update(filenames(item))
    return found


def durations(value: Any) -> set[float]:
    found = set()
    value = normalize_json(value)
    if isinstance(value, dict):
        if "duration" in value:
            try:
                found.add(float(value["duration"]))
            except (TypeError, ValueError):
                pass
        for item in value.values():
            found.update(durations(item))
    elif isinstance(value, list):
        for item in value:
            found.update(durations(item))
    return found


def contains_callback_data(value: Any, callback_data: str) -> bool:
    value = normalize_json(value)
    if isinstance(value, dict):
        if value.get("callback_data") == callback_data:
            return True
        return any(contains_callback_data(item, callback_data) for item in value.values())
    if isinstance(value, list):
        return any(contains_callback_data(item, callback_data) for item in value)
    return False


def normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


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
    return None if value is None else str(value)
