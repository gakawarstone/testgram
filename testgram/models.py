from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class FakeUser:
    id: int
    first_name: str = "Test"
    username: str | None = "test_user"
    is_bot: bool = False
    last_name: str | None = None
    language_code: str | None = None
    is_premium: bool | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any] | None,
        *,
        default_id: int,
        default_username: str = "test_user",
        default_first_name: str = "Test",
    ) -> FakeUser:
        payload = payload or {}
        return cls(
            id=int(payload.get("id", default_id)),
            first_name=str(payload.get("first_name", default_first_name)),
            username=_optional_str(payload.get("username", default_username)),
            is_bot=bool(payload.get("is_bot", False)),
            last_name=_optional_str(payload.get("last_name")),
            language_code=_optional_str(payload.get("language_code")),
            is_premium=_optional_bool(payload.get("is_premium")),
        )

    def to_telegram(self) -> dict[str, Any]:
        user: dict[str, Any] = {
            "id": self.id,
            "is_bot": self.is_bot,
            "first_name": self.first_name,
        }
        _include_optional(
            user,
            username=self.username,
            last_name=self.last_name,
            language_code=self.language_code,
            is_premium=self.is_premium,
        )
        return user


@dataclass(slots=True)
class FakeChat:
    id: int
    type: str = "private"
    first_name: str | None = "Test"
    username: str | None = "test_user"
    last_name: str | None = None
    title: str | None = None
    is_forum: bool | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any] | None,
        *,
        default_id: int,
        user: FakeUser,
    ) -> FakeChat:
        payload = payload or {}
        chat_type = str(payload.get("type", "private"))
        is_private = chat_type == "private"
        return cls(
            id=int(payload.get("id", default_id)),
            type=chat_type,
            first_name=_optional_str(
                payload.get("first_name", user.first_name if is_private else None)
            ),
            username=_optional_str(
                payload.get("username", user.username if is_private else None)
            ),
            last_name=_optional_str(
                payload.get("last_name", user.last_name if is_private else None)
            ),
            title=_optional_str(
                payload.get("title", "Test group" if not is_private else None)
            ),
            is_forum=_optional_bool(payload.get("is_forum")),
        )

    def to_telegram(self) -> dict[str, Any]:
        chat: dict[str, Any] = {"id": self.id, "type": self.type}
        _include_optional(
            chat,
            first_name=self.first_name,
            username=self.username,
            last_name=self.last_name,
            title=self.title,
            is_forum=self.is_forum,
        )
        return chat


@dataclass(slots=True)
class FakeMessage:
    message_id: int
    chat: FakeChat
    from_user: FakeUser
    fields: dict[str, Any]
    date: int = field(default_factory=lambda: int(time()))

    def to_telegram(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "message_id": self.message_id,
            "from": self.from_user.to_telegram(),
            "chat": self.chat.to_telegram(),
            "date": self.date,
            **self.fields,
        }
        text = message.get("text")
        if isinstance(text, str) and "entities" not in message:
            command = text.split(maxsplit=1)[0]
            if command.startswith("/") and len(command) > 1:
                message["entities"] = [
                    {"type": "bot_command", "offset": 0, "length": len(command)}
                ]
        return message


@dataclass(slots=True)
class FakeInlineQuery:
    id: str
    from_user: FakeUser
    query: str
    offset: str = ""
    chat_type: str | None = None
    location: dict[str, Any] | None = None

    def to_telegram(self) -> dict[str, Any]:
        query: dict[str, Any] = {
            "id": self.id,
            "from": self.from_user.to_telegram(),
            "query": self.query,
            "offset": self.offset,
        }
        _include_optional(query, chat_type=self.chat_type, location=self.location)
        return query


@dataclass(slots=True)
class FakeUpdate:
    update_id: int
    message: FakeMessage | None = None
    callback_query: FakeCallbackQuery | None = None
    inline_query: FakeInlineQuery | None = None
    raw_fields: dict[str, Any] = field(default_factory=dict)

    def to_telegram(self) -> dict[str, Any]:
        update: dict[str, Any] = {"update_id": self.update_id, **self.raw_fields}
        if self.message is not None:
            update["message"] = self.message.to_telegram()
        if self.callback_query is not None:
            update["callback_query"] = self.callback_query.to_telegram()
        if self.inline_query is not None:
            update["inline_query"] = self.inline_query.to_telegram()
        return update


@dataclass(slots=True)
class FakeCallbackQuery:
    id: str
    from_user: FakeUser
    message: dict[str, Any]
    data: str
    chat_instance: str

    def to_telegram(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from": self.from_user.to_telegram(),
            "message": self.message,
            "chat_instance": self.chat_instance,
            "data": self.data,
        }


def _include_optional(target: dict[str, Any], **values: Any) -> None:
    target.update({key: value for key, value in values.items() if value is not None})


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)
