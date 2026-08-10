from __future__ import annotations

import unittest

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.scenario.expectations import ChatBotMessagesExpectation, MessageMatcher
from testgram.server import RunningServer, start_server


class CallbackFlowTests(unittest.IsolatedAsyncioTestCase):
    server: RunningServer

    async def asyncSetUp(self) -> None:
        self.server = await start_server("127.0.0.1", 0, quiet=True)

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def test_click_injects_and_records_complete_callback_query(self) -> None:
        client = TestgramClient(
            self.server.url,
            chat_id=42,
            username="alice",
            first_name="Alice",
        )
        reply_markup = {
            "inline_keyboard": [
                [{"text": "Open", "callback_data": "settings:open"}]
            ]
        }

        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123/sendMessage",
                json={
                    "chat_id": 42,
                    "text": "Settings",
                    "reply_markup": reply_markup,
                },
            ) as response:
                response.raise_for_status()
                source_message = (await response.json())["result"]

            source_event = await client.click(session, "settings:open")
            self.assertEqual(source_event, 0)

            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                response.raise_for_status()
                updates = (await response.json())["result"]
            events = await client.get_events(session)

        callback = updates[-1]["callback_query"]
        self.assertEqual(callback["data"], "settings:open")
        self.assertEqual(callback["from"]["username"], "alice")
        self.assertEqual(callback["message"], source_message)
        self.assertEqual(callback["message"]["chat"]["id"], 42)
        self.assertEqual(events[1]["type"], "callback_query")
        self.assertEqual(events[1]["payload"], updates[-1])


class ExpandedUpdateFlowTests(unittest.IsolatedAsyncioTestCase):
    server: RunningServer

    async def asyncSetUp(self) -> None:
        self.server = await start_server("127.0.0.1", 0, quiet=True)

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def test_media_group_identity_and_administrators(self) -> None:
        client = TestgramClient(self.server.url, chat_id=-100, username="fallback")
        chat = {"id": -100, "type": "supergroup", "title": "GKBot tests"}
        user = {
            "id": 42,
            "first_name": "Alice",
            "last_name": "Tester",
            "username": "alice",
            "language_code": "en",
        }
        administrators = [
            {"id": 7, "first_name": "Owner", "username": "owner", "status": "creator"},
            {"user": {"id": 8, "first_name": "Mod", "username": "mod"}},
        ]

        async with ClientSession() as session:
            await client.send(
                session,
                {
                    "document": {
                        "file_id": "document-id",
                        "file_unique_id": "document-unique",
                        "file_name": "input.xlsx",
                        "mime_type": "application/vnd.ms-excel",
                    },
                    "caption": "Import",
                    "user": user,
                    "chat": chat,
                    "administrators": administrators,
                },
            )
            await client.send(
                session,
                {"photo": {"file_id": "photo-id", "width": 640, "height": 480}, "chat": chat},
            )
            await client.send(
                session,
                {"audio": {"file_id": "audio-id", "duration": 12, "title": "Clip"}, "chat": chat},
            )
            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                updates = (await response.json())["result"]
            async with session.post(
                f"{self.server.url}/bot123/getChatAdministrators",
                json={"chat_id": -100},
            ) as response:
                admins = (await response.json())["result"]

        document = updates[0]["message"]
        self.assertEqual(document["from"]["id"], 42)
        self.assertEqual(document["from"]["last_name"], "Tester")
        self.assertEqual(document["chat"], {"id": -100, "type": "supergroup", "title": "GKBot tests"})
        self.assertEqual(document["document"]["file_name"], "input.xlsx")
        self.assertEqual(document["caption"], "Import")
        self.assertEqual(updates[1]["message"]["photo"][0]["width"], 640)
        self.assertEqual(updates[2]["message"]["audio"]["duration"], 12)
        self.assertEqual([admin["user"]["username"] for admin in admins], ["owner", "mod"])
        self.assertEqual(admins[0]["status"], "creator")

    async def test_inline_query_and_raw_update_are_delivered(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)
        async with ClientSession() as session:
            await client.send_inline_query(
                session,
                {
                    "id": "query-1",
                    "query": "lst red blue",
                    "offset": "next",
                    "chat_type": "group",
                    "user": {"id": 77, "first_name": "Inline", "username": "inline"},
                },
            )
            await client.send_raw_update(
                session,
                {
                    "my_chat_member": {
                        "chat": {"id": -200, "type": "group", "title": "Raw"},
                        "from": {"id": 77, "is_bot": False, "first_name": "Inline"},
                        "date": 1,
                        "old_chat_member": {"status": "left", "user": {"id": 999, "is_bot": True, "first_name": "Bot"}},
                        "new_chat_member": {"status": "member", "user": {"id": 999, "is_bot": True, "first_name": "Bot"}},
                    }
                },
            )
            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                updates = (await response.json())["result"]
            events = await client.get_events(session)

        inline_query = updates[0]["inline_query"]
        self.assertEqual(inline_query["id"], "query-1")
        self.assertEqual(inline_query["from"]["id"], 77)
        self.assertEqual(inline_query["query"], "lst red blue")
        self.assertEqual(inline_query["chat_type"], "group")
        self.assertEqual(updates[1]["update_id"], updates[0]["update_id"] + 1)
        self.assertEqual(updates[1]["my_chat_member"]["chat"]["id"], -200)
        self.assertEqual([event["type"] for event in events], ["inline_query", "telegram_update", "bot_api_request"])


class StructuredExpectationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.event = {
            "type": "bot_api_request",
            "payload": {
                "method": "sendVideo",
                "payload": {
                    "chat_id": "42",
                    "video": {"filename": "result.mp4"},
                    "duration": "12",
                    "caption": "Ready",
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "Play", "callback_data": "play:1"}]
                        ]
                    },
                },
            },
        }

    def test_all_structured_fields_match(self) -> None:
        matcher = MessageMatcher.from_payload(
            {
                "reply_markup": self.event["payload"]["payload"]["reply_markup"],
                "callback_data": "play:1",
                "media_type": "video",
                "filename": "result.mp4",
                "duration": 12,
                "caption": "Ready",
                "parse_mode": "HTML",
                "chat_id": 42,
            }
        )
        self.assertTrue(matcher.matches(self.event))

    def test_chat_message_sequence_is_ordered(self) -> None:
        first = {
            "type": "bot_api_request",
            "payload": {
                "method": "sendMessage",
                "payload": {"chat_id": 42, "text": "Preparing"},
            },
        }
        expectation = ChatBotMessagesExpectation.from_payload(
            {"messages": [{"text": "Preparing"}, {"media_type": "video"}]}
        )
        client = TestgramClient("http://unused", chat_id=42)
        self.assertTrue(expectation.matches(client, [first, self.event]))
        self.assertFalse(expectation.matches(client, [self.event, first]))


if __name__ == "__main__":
    unittest.main()
