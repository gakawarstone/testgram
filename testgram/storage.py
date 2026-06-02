from __future__ import annotations

import asyncio
from typing import Any

from .models import FakeChat, FakeMessage, FakeUpdate, FakeUser


class MemoryStorage:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._events: list[dict[str, Any]] = []
        self._updates: list[FakeUpdate] = []
        self._next_update_id = 1
        self._next_message_id = 1
        self._next_bot_message_id = 10_000

    async def add_event(self, event: dict[str, Any]) -> None:
        async with self._condition:
            self._events.append(event)

    async def get_events(self) -> list[dict[str, Any]]:
        async with self._condition:
            return list(self._events)

    async def create_user_message(
        self,
        chat_id: int,
        text: str,
        username: str = "test_user",
        first_name: str = "Test",
    ) -> FakeUpdate:
        async with self._condition:
            chat = FakeChat(id=chat_id, username=username, first_name=first_name)
            from_user = FakeUser(id=chat_id, username=username, first_name=first_name)
            message = FakeMessage(
                message_id=self._next_message_id,
                chat=chat,
                text=text,
                from_user=from_user,
            )
            update = FakeUpdate(update_id=self._next_update_id, message=message)
            self._next_message_id += 1
            self._next_update_id += 1
            self._updates.append(update)
            self._condition.notify_all()
            return update

    async def get_updates(self, offset: int | None, limit: int, timeout: int) -> list[dict[str, Any]]:
        async with self._condition:
            if timeout > 0 and not self._select_updates(offset, limit):
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout)
                except TimeoutError:
                    return []

            return [update.to_telegram() for update in self._select_updates(offset, limit)]

    async def next_bot_message_id(self) -> int:
        async with self._condition:
            message_id = self._next_bot_message_id
            self._next_bot_message_id += 1
            return message_id

    async def reset(self) -> None:
        async with self._condition:
            self._events.clear()
            self._updates.clear()
            self._condition.notify_all()

    def _select_updates(self, offset: int | None, limit: int) -> list[FakeUpdate]:
        updates = self._updates
        if offset is not None:
            updates = [update for update in updates if update.update_id >= offset]
        return updates[:limit]
