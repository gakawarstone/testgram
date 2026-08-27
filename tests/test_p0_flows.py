from __future__ import annotations

import asyncio
import unittest

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.scenario.expectations import (
    ChatBotMessagesExpectation,
    MessageMatcher,
    NoneExpectation,
)
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

    async def test_update_is_consumed_only_after_offset_advances(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)

        async with ClientSession() as session:
            update_id = await client.send_message(session, "/start")
            waiter = asyncio.create_task(
                client.wait_for_update_consumed(session, update_id, timeout=1)
            )

            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                response.raise_for_status()
                self.assertEqual(
                    (await response.json())["result"][0]["update_id"], update_id
                )
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())

            async with session.post(
                f"{self.server.url}/bot123/getUpdates",
                json={"offset": update_id + 1},
            ) as response:
                response.raise_for_status()
            await waiter

    async def test_expect_none_observes_the_whole_window(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)
        expectation = NoneExpectation.from_payload(
            {"text": "forbidden", "duration": 0.3}, default_timeout=1
        )

        async with ClientSession() as session:
            async def delayed_reply() -> None:
                await asyncio.sleep(0.1)
                async with session.post(
                    f"{self.server.url}/bot123/sendMessage",
                    json={"chat_id": 42, "text": "forbidden"},
                ) as response:
                    response.raise_for_status()

            task = asyncio.create_task(delayed_reply())
            violation, _ = await expectation.observe(client, session, seen_events=0)
            await task

        self.assertIsNotNone(violation)


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
