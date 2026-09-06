from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Protocol

from aiohttp import ClientSession


BOT_MESSAGE_METHODS = {
    "sendMessage",
    "sendPhoto",
    "sendDocument",
    "sendVideo",
    "sendAudio",
    "sendVoice",
    "sendAnimation",
    "sendSticker",
    "sendMediaGroup",
    "editMessageText",
    "editMessageCaption",
    "editMessageMedia",
    "editMessageReplyMarkup",
}


class BotEventMatcher(Protocol):
    def matches(self, event: dict[str, Any]) -> bool: ...


class TestgramClient:
    def __init__(
        self,
        base_url: str,
        chat_id: int,
        username: str = "test_user",
        first_name: str = "Test",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_id = chat_id
        self.username = username
        self.first_name = first_name

    async def reset(self, session: ClientSession) -> None:
        async with session.post(f"{self.base_url}/testgram/reset") as response:
            response.raise_for_status()

    async def get_events(self, session: ClientSession) -> list[dict[str, Any]]:
        async with session.get(f"{self.base_url}/testgram/events") as response:
            response.raise_for_status()
            payload = await response.json()
        return payload["result"]

    async def send_message(self, session: ClientSession, text: str) -> int:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "username": self.username,
            "first_name": self.first_name,
        }
        async with session.post(
            f"{self.base_url}/testgram/messages", json=payload
        ) as response:
            response.raise_for_status()
            result = (await response.json())["result"]
        return int(result["update_id"])

    async def wait_for_update_consumed(
        self,
        session: ClientSession,
        update_id: int,
        timeout: float,
    ) -> None:
        async with session.get(
            f"{self.base_url}/testgram/updates/{update_id}/consumed",
            params={"timeout": timeout},
        ) as response:
            response.raise_for_status()
            status = (await response.json())["result"]
        if not status["consumed"]:
            raise TimeoutError(
                f"update {update_id} was not consumed within {timeout:g}s"
            )

    async def click(
        self,
        session: ClientSession,
        callback_data: str | None = None,
        message_id: int | None = None,
        wait_consumed: bool = False,
        timeout: float = 0,
        *,
        callback_data_regex: str | None = None,
        button_text: str | None = None,
        message_matcher: BotEventMatcher | None = None,
    ) -> int:
        source = self._find_callback_source(
            await self.get_events(session),
            callback_data=callback_data,
            callback_data_regex=callback_data_regex,
            button_text=button_text,
            message_id=message_id,
            message_matcher=message_matcher,
        )
        if source is None:
            detail = f" in message {message_id}" if message_id is not None else ""
            selector = _describe_button_selector(
                callback_data=callback_data,
                callback_data_regex=callback_data_regex,
                button_text=button_text,
            )
            raise ValueError(f"{selector} was not found{detail}")

        source_index, source_message, matched_callback_data = source
        payload = {
            "chat_id": self.chat_id,
            "data": matched_callback_data,
            "message": source_message,
            "username": self.username,
            "first_name": self.first_name,
        }
        async with session.post(
            f"{self.base_url}/testgram/callbacks", json=payload
        ) as response:
            response.raise_for_status()
            update = (await response.json())["result"]
        if wait_consumed:
            await self.wait_for_update_consumed(
                session, int(update["update_id"]), timeout
            )
        return source_index

    def _find_callback_source(
        self,
        events: list[dict[str, Any]],
        *,
        callback_data: str | None,
        callback_data_regex: str | None,
        button_text: str | None,
        message_id: int | None,
        message_matcher: BotEventMatcher | None,
    ) -> tuple[int, dict[str, Any], str] | None:
        callback_pattern = (
            re.compile(callback_data_regex) if callback_data_regex is not None else None
        )
        for event_index in range(len(events) - 1, -1, -1):
            event = events[event_index]
            if not self.is_bot_reply(event):
                continue
            if message_matcher is not None and not message_matcher.matches(event):
                continue
            event_payload = event.get("payload", {})
            request_payload = event_payload.get("payload", {})
            matched_callback_data = _find_button_callback_data(
                request_payload.get("reply_markup"),
                callback_data=callback_data,
                callback_pattern=callback_pattern,
                button_text=button_text,
            )
            if matched_callback_data is None:
                continue
            result = event_payload.get("response", {}).get("result")
            messages = result if isinstance(result, list) else [result]
            for message in reversed(messages):
                if not isinstance(message, dict):
                    continue
                if message_id is not None and message.get("message_id") != message_id:
                    continue
                source = dict(message)
                source.setdefault("reply_markup", request_payload.get("reply_markup"))
                return event_index, source, matched_callback_data
        return None

    async def wait_for_bot_events(
        self,
        session: ClientSession,
        seen_events: int,
        timeout: float,
    ) -> tuple[list[tuple[int, dict[str, Any]]], int]:
        deadline = asyncio.get_running_loop().time() + timeout

        while asyncio.get_running_loop().time() < deadline:
            events = await self.get_events(session)
            new_bot_events = [
                (index, event)
                for index, event in enumerate(events[seen_events:], start=seen_events)
                if self.is_bot_reply(event)
            ]
            if new_bot_events:
                return new_bot_events, seen_events

            seen_events = len(events)
            await asyncio.sleep(0.2)

        return [], seen_events

    def is_bot_reply(self, event: dict[str, Any]) -> bool:
        if event.get("type") != "bot_api_request":
            return False

        payload = event.get("payload", {})
        if payload.get("method") not in BOT_MESSAGE_METHODS:
            return False

        request_payload = payload.get("payload", {})
        chat_id = request_payload.get("chat_id")
        return chat_id is None or str(chat_id) == str(self.chat_id)

    def format_bot_reply(self, event: dict[str, Any]) -> str:
        payload = event["payload"]
        method = payload["method"]
        request_payload = payload["payload"]

        text = request_payload.get("text") or request_payload.get("caption")
        if text:
            return str(text)

        if method == "sendMediaGroup":
            media = request_payload.get("media", "[]")
            return f"[{method}] {media}"

        return f"[{method}]"


def _find_button_callback_data(
    value: Any,
    *,
    callback_data: str | None,
    callback_pattern: re.Pattern[str] | None,
    button_text: str | None,
) -> str | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        candidate = value.get("callback_data")
        if isinstance(candidate, str):
            if callback_data is not None and candidate == callback_data:
                return candidate
            if callback_pattern is not None and callback_pattern.search(candidate):
                return candidate
            if button_text is not None and str(value.get("text")) == button_text:
                return candidate
        for item in value.values():
            found = _find_button_callback_data(
                item,
                callback_data=callback_data,
                callback_pattern=callback_pattern,
                button_text=button_text,
            )
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_button_callback_data(
                item,
                callback_data=callback_data,
                callback_pattern=callback_pattern,
                button_text=button_text,
            )
            if found is not None:
                return found
    return None


def _describe_button_selector(
    *,
    callback_data: str | None,
    callback_data_regex: str | None,
    button_text: str | None,
) -> str:
    if callback_data is not None:
        return f"callback_data {callback_data!r}"
    if callback_data_regex is not None:
        return f"callback_data matching {callback_data_regex!r}"
    return f"button text {button_text!r}"
