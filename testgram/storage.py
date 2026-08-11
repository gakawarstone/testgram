from __future__ import annotations

import asyncio
import math
from time import time
from typing import Any

from .models import FakeCallbackQuery, FakeChat, FakeMessage, FakeUpdate, FakeUser


class MemoryStorage:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._events: list[dict[str, Any]] = []
        self._updates: list[FakeUpdate] = []
        self._consumed_update_id = 0
        self._next_update_id = 1
        self._next_message_id = 1
        self._next_bot_message_id = 10_000
        self._now = float(time())
        self._clock_revision = 0

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
                date=int(self._now),
            )
            update = FakeUpdate(update_id=self._next_update_id, message=message)
            self._next_message_id += 1
            self._next_update_id += 1
            self._updates.append(update)
            self._condition.notify_all()
            return update

    async def create_callback_query(
        self,
        *,
        data: str,
        message: dict[str, Any],
        chat_id: int,
        username: str = "test_user",
        first_name: str = "Test",
    ) -> FakeUpdate:
        async with self._condition:
            callback_query = FakeCallbackQuery(
                id=f"testgram-callback-{self._next_update_id}",
                from_user=FakeUser(
                    id=chat_id,
                    username=username,
                    first_name=first_name,
                ),
                message=message,
                data=data,
                chat_instance=f"testgram-chat-{chat_id}",
            )
            update = FakeUpdate(
                update_id=self._next_update_id,
                callback_query=callback_query,
            )
            self._next_update_id += 1
            self._updates.append(update)
            self._condition.notify_all()
            return update

    async def get_updates(self, offset: int | None, limit: int, timeout: int) -> list[dict[str, Any]]:
        async with self._condition:
            confirmed = min((offset or 1) - 1, self._next_update_id - 1)
            if confirmed > self._consumed_update_id:
                self._consumed_update_id = confirmed
                self._condition.notify_all()
            if timeout > 0 and not self._select_updates(offset, limit):
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout)
                except TimeoutError:
                    return []

            return [update.to_telegram() for update in self._select_updates(offset, limit)]

    async def wait_for_update_consumed(self, update_id: int, timeout: float) -> bool:
        """Wait until getUpdates confirms all updates through ``update_id``."""
        async with self._condition:
            if self._consumed_update_id >= update_id:
                return True
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(
                        lambda: self._consumed_update_id >= update_id
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                return False
            return True

    async def update_status(self, update_id: int) -> dict[str, Any] | None:
        async with self._condition:
            if not any(update.update_id == update_id for update in self._updates):
                return None
            return {
                "update_id": update_id,
                "consumed": self._consumed_update_id >= update_id,
            }

    async def clock(self) -> dict[str, int | float]:
        async with self._condition:
            return {"unix": self._now, "revision": self._clock_revision}

    async def wait_until(self, target: float, timeout: float) -> dict[str, int | float]:
        async with self._condition:
            if self._now < target:
                try:
                    await asyncio.wait_for(
                        self._condition.wait_for(lambda: self._now >= target),
                        timeout=timeout,
                    )
                except TimeoutError:
                    pass
            return {"unix": self._now, "revision": self._clock_revision}

    async def advance_clock(self, seconds: float) -> dict[str, int | float]:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("seconds must be non-negative")
        async with self._condition:
            self._now += seconds
            self._clock_revision += 1
            self._condition.notify_all()
            return {"unix": self._now, "revision": self._clock_revision}

    async def now(self) -> float:
        async with self._condition:
            return self._now

    async def next_bot_message_id(self) -> int:
        async with self._condition:
            message_id = self._next_bot_message_id
            self._next_bot_message_id += 1
            return message_id

    async def reset(self) -> None:
        async with self._condition:
            self._events.clear()
            self._updates.clear()
            self._consumed_update_id = self._next_update_id - 1
            self._now = float(time())
            self._clock_revision += 1
            self._condition.notify_all()

    def _select_updates(self, offset: int | None, limit: int) -> list[FakeUpdate]:
        updates = self._updates
        if offset is not None:
            updates = [update for update in updates if update.update_id >= offset]
        return updates[:limit]
