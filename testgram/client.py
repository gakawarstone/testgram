from __future__ import annotations

import asyncio
from typing import Any

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
    "answerInlineQuery",
}


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
        self.chat_ids = {chat_id}

    async def reset(self, session: ClientSession) -> None:
        async with session.post(f"{self.base_url}/testgram/reset") as response:
            response.raise_for_status()

    async def get_events(self, session: ClientSession) -> list[dict[str, Any]]:
        async with session.get(f"{self.base_url}/testgram/events") as response:
            response.raise_for_status()
            payload = await response.json()
        return payload["result"]

    async def send_message(self, session: ClientSession, text: str) -> None:
        await self.send(session, {"text": text})

    async def send(
        self, session: ClientSession, message: dict[str, Any]
    ) -> None:
        payload = {
            "chat_id": self.chat_id,
            "username": self.username,
            "first_name": self.first_name,
            **message,
        }
        chat = payload.get("chat")
        if isinstance(chat, dict) and chat.get("id") is not None:
            self.chat_ids.add(int(chat["id"]))
        else:
            self.chat_ids.add(int(payload.get("chat_id", self.chat_id)))
        async with session.post(f"{self.base_url}/testgram/messages", json=payload) as response:
            response.raise_for_status()

    async def send_inline_query(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        request_payload = {
            "user_id": self.chat_id,
            "username": self.username,
            "first_name": self.first_name,
            **payload,
        }
        async with session.post(
            f"{self.base_url}/testgram/inline-queries", json=request_payload
        ) as response:
            response.raise_for_status()

    async def send_raw_update(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        for field in (
            "message",
            "edited_message",
            "channel_post",
            "edited_channel_post",
            "my_chat_member",
            "chat_member",
            "chat_join_request",
        ):
            value = payload.get(field)
            chat = value.get("chat") if isinstance(value, dict) else None
            if isinstance(chat, dict) and chat.get("id") is not None:
                self.chat_ids.add(int(chat["id"]))
        async with session.post(
            f"{self.base_url}/testgram/updates", json=payload
        ) as response:
            response.raise_for_status()

    async def click(
        self,
        session: ClientSession,
        callback_data: str,
        message_id: int | None = None,
        user: dict[str, Any] | None = None,
    ) -> int:
        source = self._find_callback_source(
            await self.get_events(session),
            callback_data=callback_data,
            message_id=message_id,
        )
        if source is None:
            detail = f" in message {message_id}" if message_id is not None else ""
            raise ValueError(f"callback_data {callback_data!r} was not found{detail}")

        source_index, source_message = source
        payload = {
            "chat_id": source_message.get("chat", {}).get("id", self.chat_id),
            "data": callback_data,
            "message": source_message,
            "username": self.username,
            "first_name": self.first_name,
        }
        if user is not None:
            payload["user"] = user
        async with session.post(
            f"{self.base_url}/testgram/callbacks", json=payload
        ) as response:
            response.raise_for_status()
        return source_index

    def _find_callback_source(
        self,
        events: list[dict[str, Any]],
        *,
        callback_data: str,
        message_id: int | None,
    ) -> tuple[int, dict[str, Any]] | None:
        for event_index in range(len(events) - 1, -1, -1):
            event = events[event_index]
            if not self.is_bot_reply(event):
                continue
            event_payload = event.get("payload", {})
            request_payload = event_payload.get("payload", {})
            if not _contains_callback_data(
                request_payload.get("reply_markup"), callback_data
            ):
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
                return event_index, source
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
        return chat_id is None or any(str(chat_id) == str(item) for item in self.chat_ids)

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


def _contains_callback_data(value: Any, callback_data: str) -> bool:
    if isinstance(value, str):
        try:
            import json

            value = json.loads(value)
        except ValueError:
            return False
    if isinstance(value, dict):
        if value.get("callback_data") == callback_data:
            return True
        return any(_contains_callback_data(item, callback_data) for item in value.values())
    if isinstance(value, list):
        return any(_contains_callback_data(item, callback_data) for item in value)
    return False
