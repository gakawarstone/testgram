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
    "sendMediaGroup",
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

    async def reset(self, session: ClientSession) -> None:
        async with session.post(f"{self.base_url}/testgram/reset") as response:
            response.raise_for_status()

    async def get_events(self, session: ClientSession) -> list[dict[str, Any]]:
        async with session.get(f"{self.base_url}/testgram/events") as response:
            response.raise_for_status()
            payload = await response.json()
        return payload["result"]

    async def send_message(self, session: ClientSession, text: str) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "username": self.username,
            "first_name": self.first_name,
        }
        async with session.post(f"{self.base_url}/testgram/messages", json=payload) as response:
            response.raise_for_status()

    async def wait_for_bot_events(
        self,
        session: ClientSession,
        seen_events: int,
        timeout: float,
    ) -> tuple[list[dict[str, Any]], int]:
        deadline = asyncio.get_running_loop().time() + timeout

        while asyncio.get_running_loop().time() < deadline:
            events = await self.get_events(session)
            new_bot_events = [
                event for event in events[seen_events:] if self.is_bot_reply(event)
            ]
            if new_bot_events:
                return new_bot_events, len(events)

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
