from __future__ import annotations

from typing import Any

from aiohttp import web

from .console import EventLogger
from .storage import MemoryStorage


class TelegramApi:
    def __init__(self, storage: MemoryStorage, logger: EventLogger) -> None:
        self._storage = storage
        self._logger = logger

    async def handle_method(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        method = request.match_info["method"]
        payload = await self._read_payload(request)

        handler = getattr(self, f"_method_{method}", None)
        if handler is None:
            result = True
        else:
            result = await handler(payload)

        event = await self._logger.write(
            "bot_api_request",
            {
                "token": token,
                "method": method,
                "payload": payload,
                "response": {"ok": True, "result": result},
            },
        )
        await self._storage.add_event(event)

        return self._ok(result)

    async def create_message(self, request: web.Request) -> web.Response:
        payload = await request.json()
        chat_id = int(payload.get("chat_id", 1))
        text = str(payload["text"])
        username = str(payload.get("username", "test_user"))
        first_name = str(payload.get("first_name", "Test"))

        update = await self._storage.create_user_message(
            chat_id=chat_id,
            text=text,
            username=username,
            first_name=first_name,
        )
        event = await self._logger.write("user_message", update.to_telegram())
        await self._storage.add_event(event)
        return self._ok(update.to_telegram())

    async def get_events(self, request: web.Request) -> web.Response:
        events = await self._storage.get_events()
        return self._ok(events)

    async def reset(self, request: web.Request) -> web.Response:
        await self._storage.reset()
        event = await self._logger.write("reset", {})
        await self._storage.add_event(event)
        return self._ok(True)

    async def health(self, request: web.Request) -> web.Response:
        return self._ok({"status": "ok"})

    async def _method_getMe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": 999_001,
            "is_bot": True,
            "first_name": "Testgram Bot",
            "username": "testgram_bot",
            "can_join_groups": True,
            "can_read_all_group_messages": False,
            "supports_inline_queries": True,
        }

    async def _method_getUpdates(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        offset = self._optional_int(payload.get("offset"))
        limit = self._optional_int(payload.get("limit")) or 100
        timeout = self._optional_int(payload.get("timeout")) or 0
        return await self._storage.get_updates(offset=offset, limit=limit, timeout=timeout)

    async def _method_sendMessage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(payload, text=str(payload.get("text", "")))

    async def _method_editMessageText(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_deleteMessage(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_answerCallbackQuery(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_setMyCommands(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_deleteWebhook(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_sendChatAction(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_sendPhoto(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            photo=[
                {
                    "file_id": "testgram-photo",
                    "file_unique_id": "testgram-photo-unique",
                    "width": 1,
                    "height": 1,
                }
            ],
        )

    async def _method_sendDocument(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            document={
                "file_id": "testgram-document",
                "file_unique_id": "testgram-document-unique",
            },
        )

    async def _method_sendVideo(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            video={
                "file_id": "testgram-video",
                "file_unique_id": "testgram-video-unique",
                "width": 1,
                "height": 1,
                "duration": 1,
            },
        )

    async def _method_sendAudio(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            audio={
                "file_id": "testgram-audio",
                "file_unique_id": "testgram-audio-unique",
                "duration": 1,
            },
        )

    async def _method_sendVoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            voice={
                "file_id": "testgram-voice",
                "file_unique_id": "testgram-voice-unique",
                "duration": 1,
            },
        )

    async def _method_sendMediaGroup(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        media = payload.get("media", [])
        if not isinstance(media, list):
            media = []
        return [await self._bot_message(payload, media=item) for item in media]

    async def _method_answerInlineQuery(self, payload: dict[str, Any]) -> bool:
        return True

    async def _bot_message(self, payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
        chat_id = self._optional_int(payload.get("chat_id")) or 1
        message = {
            "message_id": await self._storage.next_bot_message_id(),
            "from": {
                "id": 999_001,
                "is_bot": True,
                "first_name": "Testgram Bot",
                "username": "testgram_bot",
            },
            "chat": {
                "id": chat_id,
                "type": "private",
            },
            "date": 1,
        }
        message.update({key: value for key, value in extra.items() if value is not None})
        return message

    async def _read_payload(self, request: web.Request) -> dict[str, Any]:
        if request.content_type == "application/json":
            payload = await request.json()
            if isinstance(payload, dict):
                return payload
            return {"value": payload}

        post = await request.post()
        return dict(post.items())

    def _ok(self, result: Any) -> web.Response:
        return web.json_response({"ok": True, "result": result})

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)
