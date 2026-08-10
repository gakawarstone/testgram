from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from aiohttp import ClientSession

from testgram.chat import open_chat
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

    async def test_polling_readiness_precedes_chat_event_baseline(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)

        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot-old/getUpdates",
                json={},
            ) as response:
                response.raise_for_status()
            polling_count = await client.get_polling_count(session)

            async with session.post(
                f"{self.server.url}/bot123/sendMessage",
                json={"chat_id": 42, "text": "bot started"},
            ) as response:
                response.raise_for_status()

            async def long_poll() -> None:
                async with session.post(
                    f"{self.server.url}/bot123/getUpdates",
                    json={"timeout": 2},
                ) as response:
                    response.raise_for_status()
                    await response.json()

            poll_task = asyncio.create_task(long_poll())
            await client.wait_for_polling(
                session,
                timeout=0.5,
                after=polling_count,
            )

            self.assertFalse(poll_task.done())
            events = await client.get_events(session)
            self.assertEqual(len(events), 2)
            self.assertEqual(
                events[-1]["payload"]["payload"]["text"],
                "bot started",
            )

            await client.send_message(session, "/list")
            await poll_task

    async def test_chat_does_not_treat_startup_message_as_command_response(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)

        async def run_bot() -> None:
            async with ClientSession() as session:
                async with session.post(
                    f"{self.server.url}/bot123/sendMessage",
                    json={"chat_id": 42, "text": "bot started"},
                ) as response:
                    response.raise_for_status()
                async with session.post(
                    f"{self.server.url}/bot123/getUpdates",
                    json={"timeout": 2},
                ) as response:
                    response.raise_for_status()
                    await response.json()
                async with session.post(
                    f"{self.server.url}/bot123/sendMessage",
                    json={"chat_id": 42, "text": "the /list response"},
                ) as response:
                    response.raise_for_status()

        bot_task = asyncio.create_task(run_bot())
        output = io.StringIO()
        with patch("builtins.input", side_effect=["/list", "/exit"]):
            with redirect_stdout(output):
                await open_chat(
                    client,
                    timeout=1,
                    reset=False,
                    polling_after=0,
                )
        await bot_task

        self.assertNotIn("bot: bot started", output.getvalue())
        self.assertIn("bot: the /list response", output.getvalue())


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
