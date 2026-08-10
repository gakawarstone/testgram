from __future__ import annotations

from typing import Any

from aiohttp import web
from aiohttp.web_request import FileField

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
        chat_payload = self._optional_mapping(payload.get("chat"), "chat")
        chat_id = int(chat_payload.get("id", payload.get("chat_id", 1)))
        username = str(payload.get("username", "test_user"))
        first_name = str(payload.get("first_name", "Test"))
        user_payload = self._optional_mapping(
            self._first_present(payload, "user", "from_user", "from", "identity"),
            "user",
        )
        administrators = payload.get("administrators")
        if administrators is not None and not isinstance(administrators, list):
            raise web.HTTPBadRequest(text="administrators must be a list")

        control_fields = {
            "chat_id",
            "username",
            "first_name",
            "user",
            "from_user",
            "from",
            "identity",
            "chat",
            "administrators",
        }
        fields = {
            key: value for key, value in payload.items() if key not in control_fields
        }
        for key in ("text", "caption"):
            if key in fields:
                fields[key] = str(fields[key])
        self._normalize_incoming_media(fields)
        if not any(key in fields for key in ("text", "document", "photo", "audio")):
            raise web.HTTPBadRequest(
                text="message requires one of text, document, photo, or audio"
            )

        try:
            update = await self._storage.create_user_message(
                chat_id=chat_id,
                fields=fields,
                username=username,
                first_name=first_name,
                user_payload=user_payload,
                chat_payload=chat_payload,
                administrators=administrators,
            )
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        event = await self._logger.write("user_message", update.to_telegram())
        await self._storage.add_event(event)
        return self._ok(update.to_telegram())

    async def create_callback_query(self, request: web.Request) -> web.Response:
        payload = await request.json()
        chat_id = int(payload.get("chat_id", 1))
        data = str(payload["data"])
        message = payload.get("message")
        if not isinstance(message, dict):
            raise web.HTTPBadRequest(text="message must be a mapping")

        source_chat = message.get("chat")
        if not isinstance(source_chat, dict) or str(source_chat.get("id")) != str(chat_id):
            raise web.HTTPBadRequest(text="source message does not belong to chat_id")

        update = await self._storage.create_callback_query(
            data=data,
            message=message,
            chat_id=chat_id,
            username=str(payload.get("username", "test_user")),
            first_name=str(payload.get("first_name", "Test")),
            user_payload=self._optional_mapping(
                self._first_present(payload, "user", "from_user", "from", "identity"),
                "user",
            ),
        )
        event = await self._logger.write("callback_query", update.to_telegram())
        await self._storage.add_event(event)
        return self._ok(update.to_telegram())

    async def create_inline_query(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if "query" not in payload:
            raise web.HTTPBadRequest(text="query is required")
        location = self._optional_mapping(payload.get("location"), "location")
        user_payload = self._optional_mapping(
            self._first_present(payload, "user", "from_user", "from", "identity"),
            "user",
        )
        default_user_id = int(
            user_payload.get("id", payload.get("user_id", payload.get("chat_id", 1)))
        )
        update = await self._storage.create_inline_query(
            query=str(payload["query"]),
            offset=str(payload.get("offset", "")),
            query_id=(str(payload["id"]) if payload.get("id") is not None else None),
            chat_type=(
                str(payload["chat_type"])
                if payload.get("chat_type") is not None
                else None
            ),
            location=location or None,
            user_payload=user_payload,
            default_user_id=default_user_id,
            username=str(payload.get("username", "test_user")),
            first_name=str(payload.get("first_name", "Test")),
        )
        event = await self._logger.write("inline_query", update.to_telegram())
        await self._storage.add_event(event)
        return self._ok(update.to_telegram())

    async def create_raw_update(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="update must be a mapping")
        update = await self._storage.create_raw_update(payload)
        event = await self._logger.write("telegram_update", update.to_telegram())
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

    async def _method_editMessageText(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._edited_bot_message(payload, text=payload.get("text", ""))

    async def _method_editMessageCaption(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._edited_bot_message(payload, caption=payload.get("caption", ""))

    async def _method_editMessageMedia(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._edited_bot_message(payload, media=payload.get("media"))

    async def _method_editMessageReplyMarkup(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._edited_bot_message(payload)

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
                "duration": self._optional_int(payload.get("duration")) or 1,
            },
        )

    async def _method_sendAudio(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            audio={
                "file_id": "testgram-audio",
                "file_unique_id": "testgram-audio-unique",
                "duration": self._optional_int(payload.get("duration")) or 1,
            },
        )

    async def _method_sendVoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            voice={
                "file_id": "testgram-voice",
                "file_unique_id": "testgram-voice-unique",
                "duration": self._optional_int(payload.get("duration")) or 1,
            },
        )

    async def _method_sendAnimation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            caption=payload.get("caption"),
            animation={
                "file_id": "testgram-animation",
                "file_unique_id": "testgram-animation-unique",
                "width": 1,
                "height": 1,
                "duration": self._optional_int(payload.get("duration")) or 1,
            },
        )

    async def _method_sendSticker(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._bot_message(
            payload,
            sticker={
                "file_id": "testgram-sticker",
                "file_unique_id": "testgram-sticker-unique",
                "width": 1,
                "height": 1,
                "is_animated": False,
                "is_video": False,
                "type": "regular",
            },
        )

    async def _method_sendMediaGroup(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        media = payload.get("media", [])
        if not isinstance(media, list):
            media = []
        return [await self._bot_message(payload, media=item) for item in media]

    async def _method_answerInlineQuery(self, payload: dict[str, Any]) -> bool:
        return True

    async def _method_getChatAdministrators(
        self, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return await self._storage.get_chat_administrators(payload.get("chat_id"))

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
        for key in ("reply_markup", "parse_mode"):
            if key in payload:
                message[key] = payload[key]
        return message

    async def _edited_bot_message(
        self, payload: dict[str, Any], **extra: Any
    ) -> dict[str, Any]:
        message = await self._bot_message(payload, **extra)
        message_id = self._optional_int(payload.get("message_id"))
        if message_id is not None:
            message["message_id"] = message_id
        return message

    async def _read_payload(self, request: web.Request) -> dict[str, Any]:
        if request.content_type == "application/json":
            payload = await request.json()
            if isinstance(payload, dict):
                return payload
            return {"value": payload}

        post = await request.post()
        return {
            key: self._normalize_form_value(key, value)
            for key, value in post.items()
        }

    def _normalize_form_value(self, key: str, value: Any) -> Any:
        if isinstance(value, FileField):
            return {
                "filename": value.filename,
                "content_type": value.content_type,
            }
        if key in {"reply_markup", "media", "entities", "caption_entities"}:
            try:
                import json

                return json.loads(value)
            except (TypeError, ValueError):
                return value
        return value

    def _ok(self, result: Any) -> web.Response:
        return web.json_response({"ok": True, "result": result})

    def _optional_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    def _optional_mapping(self, value: Any, name: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise web.HTTPBadRequest(text=f"{name} must be a mapping")
        return value

    def _first_present(self, payload: dict[str, Any], *keys: str) -> Any:
        return next((payload[key] for key in keys if key in payload), None)

    def _normalize_incoming_media(self, fields: dict[str, Any]) -> None:
        if "document" in fields:
            fields["document"] = self._media_object(
                fields["document"], "document", include_dimensions=False
            )
        if "audio" in fields:
            audio = self._media_object(
                fields["audio"], "audio", include_dimensions=False
            )
            audio.setdefault("duration", 1)
            fields["audio"] = audio
        if "photo" in fields:
            photo = fields["photo"]
            items = photo if isinstance(photo, list) else [photo]
            fields["photo"] = [
                self._media_object(item, "photo", include_dimensions=True)
                for item in items
            ]

    def _media_object(
        self, value: Any, media_type: str, *, include_dimensions: bool
    ) -> dict[str, Any]:
        if isinstance(value, str):
            media = {"file_id": value}
        elif isinstance(value, dict):
            media = dict(value)
        else:
            raise web.HTTPBadRequest(text=f"{media_type} must be a mapping or string")
        media.setdefault("file_id", f"testgram-{media_type}")
        media.setdefault("file_unique_id", f"testgram-{media_type}-unique")
        if include_dimensions:
            media.setdefault("width", 1)
            media.setdefault("height", 1)
        return media
