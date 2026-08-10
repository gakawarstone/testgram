from __future__ import annotations

import asyncio
from typing import Any

from .models import (
    FakeCallbackQuery,
    FakeChat,
    FakeInlineQuery,
    FakeMessage,
    FakeUpdate,
    FakeUser,
)


class MemoryStorage:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._events: list[dict[str, Any]] = []
        self._updates: list[FakeUpdate] = []
        self._next_update_id = 1
        self._next_message_id = 1
        self._next_bot_message_id = 10_000
        self._chat_administrators: dict[str, list[dict[str, Any]]] = {}

    async def add_event(self, event: dict[str, Any]) -> None:
        async with self._condition:
            self._events.append(event)

    async def get_events(self) -> list[dict[str, Any]]:
        async with self._condition:
            return list(self._events)

    async def create_user_message(
        self,
        chat_id: int,
        text: str | None = None,
        username: str = "test_user",
        first_name: str = "Test",
        *,
        fields: dict[str, Any] | None = None,
        user_payload: dict[str, Any] | None = None,
        chat_payload: dict[str, Any] | None = None,
        administrators: list[Any] | None = None,
    ) -> FakeUpdate:
        async with self._condition:
            message_fields = dict(fields or {})
            if text is not None:
                message_fields.setdefault("text", text)
            from_user = FakeUser.from_payload(
                user_payload,
                default_id=chat_id,
                default_username=username,
                default_first_name=first_name,
            )
            chat = FakeChat.from_payload(
                chat_payload,
                default_id=chat_id,
                user=from_user,
            )
            message = FakeMessage(
                message_id=self._next_message_id,
                chat=chat,
                from_user=from_user,
                fields=message_fields,
            )
            update = FakeUpdate(update_id=self._next_update_id, message=message)
            if administrators is not None:
                self._chat_administrators[str(chat.id)] = self._normalize_administrators(
                    administrators
                )
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
        user_payload: dict[str, Any] | None = None,
    ) -> FakeUpdate:
        async with self._condition:
            callback_query = FakeCallbackQuery(
                id=f"testgram-callback-{self._next_update_id}",
                from_user=FakeUser.from_payload(
                    user_payload,
                    default_id=chat_id,
                    default_username=username,
                    default_first_name=first_name,
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

    async def create_inline_query(
        self,
        *,
        query: str,
        offset: str = "",
        query_id: str | None = None,
        chat_type: str | None = None,
        location: dict[str, Any] | None = None,
        user_payload: dict[str, Any] | None = None,
        default_user_id: int = 1,
        username: str = "test_user",
        first_name: str = "Test",
    ) -> FakeUpdate:
        async with self._condition:
            inline_query = FakeInlineQuery(
                id=query_id or f"testgram-inline-{self._next_update_id}",
                from_user=FakeUser.from_payload(
                    user_payload,
                    default_id=default_user_id,
                    default_username=username,
                    default_first_name=first_name,
                ),
                query=query,
                offset=offset,
                chat_type=chat_type,
                location=location,
            )
            update = FakeUpdate(
                update_id=self._next_update_id,
                inline_query=inline_query,
            )
            self._next_update_id += 1
            self._updates.append(update)
            self._condition.notify_all()
            return update

    async def create_raw_update(self, fields: dict[str, Any]) -> FakeUpdate:
        async with self._condition:
            raw_fields = dict(fields)
            raw_fields.pop("update_id", None)
            update = FakeUpdate(
                update_id=self._next_update_id,
                raw_fields=raw_fields,
            )
            self._next_update_id += 1
            self._updates.append(update)
            self._condition.notify_all()
            return update

    async def get_chat_administrators(self, chat_id: Any) -> list[dict[str, Any]]:
        async with self._condition:
            return list(self._chat_administrators.get(str(chat_id), []))

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
            self._chat_administrators.clear()
            self._condition.notify_all()

    def _select_updates(self, offset: int | None, limit: int) -> list[FakeUpdate]:
        updates = self._updates
        if offset is not None:
            updates = [update for update in updates if update.update_id >= offset]
        return updates[:limit]

    def _normalize_administrators(
        self, administrators: list[Any]
    ) -> list[dict[str, Any]]:
        normalized = []
        for index, item in enumerate(administrators):
            if not isinstance(item, dict):
                raise ValueError("administrators entries must be mappings")
            if isinstance(item.get("user"), dict):
                member = dict(item)
                user_payload = item["user"]
            else:
                member = {"status": item.get("status", "administrator")}
                user_payload = item
            member["user"] = FakeUser.from_payload(
                user_payload,
                default_id=index + 1,
                default_username=f"admin_{index + 1}",
                default_first_name="Admin",
            ).to_telegram()
            member.setdefault("status", "administrator")
            if member["status"] in {"creator", "owner"}:
                member["status"] = "creator"
                member.setdefault("is_anonymous", False)
            elif member["status"] == "administrator":
                member.setdefault("can_be_edited", False)
                member.setdefault("is_anonymous", False)
                member.setdefault("can_manage_chat", True)
                member.setdefault("can_delete_messages", True)
                member.setdefault("can_manage_video_chats", True)
                member.setdefault("can_restrict_members", True)
                member.setdefault("can_promote_members", False)
                member.setdefault("can_change_info", True)
                member.setdefault("can_invite_users", True)
                member.setdefault("can_post_stories", True)
                member.setdefault("can_edit_stories", True)
                member.setdefault("can_delete_stories", True)
            normalized.append(member)
        return normalized
