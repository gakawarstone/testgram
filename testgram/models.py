from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class FakeUser:
    id: int
    first_name: str = "Test"
    username: str = "test_user"
    is_bot: bool = False

    def to_telegram(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "is_bot": self.is_bot,
            "first_name": self.first_name,
            "username": self.username,
        }


@dataclass(slots=True)
class FakeChat:
    id: int
    type: str = "private"
    first_name: str = "Test"
    username: str = "test_user"

    def to_telegram(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "first_name": self.first_name,
            "username": self.username,
        }


@dataclass(slots=True)
class FakeMessage:
    message_id: int
    chat: FakeChat
    text: str
    from_user: FakeUser
    date: int = field(default_factory=lambda: int(time()))

    def to_telegram(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "message_id": self.message_id,
            "from": self.from_user.to_telegram(),
            "chat": self.chat.to_telegram(),
            "date": self.date,
            "text": self.text,
        }
        command = self.text.split(maxsplit=1)[0]
        if command.startswith("/") and len(command) > 1:
            message["entities"] = [
                {
                    "type": "bot_command",
                    "offset": 0,
                    "length": len(command),
                }
            ]
        return message


@dataclass(slots=True)
class FakeUpdate:
    update_id: int
    message: FakeMessage

    def to_telegram(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "message": self.message.to_telegram(),
        }
