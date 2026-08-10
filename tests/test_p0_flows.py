from __future__ import annotations

import unittest

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.scenario.actions import ClickAction
from testgram.scenario.errors import ScenarioError
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
            "inline_keyboard": [[{"text": "Open", "callback_data": "settings:open"}]]
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

    async def test_click_selects_generated_callback_data_by_regex(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)
        reply_markup = {
            "inline_keyboard": [
                [{"text": "Open record", "callback_data": "record:48391"}]
            ]
        }

        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123/sendMessage",
                json={
                    "chat_id": 42,
                    "text": "Record created",
                    "reply_markup": reply_markup,
                },
            ) as response:
                response.raise_for_status()

            await client.click(session, callback_data_regex=r"^record:\d+$")

            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                response.raise_for_status()
                updates = (await response.json())["result"]

        self.assertEqual(updates[-1]["callback_query"]["data"], "record:48391")

    async def test_click_selects_callback_button_by_visible_text(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "Cancel", "callback_data": "cancel:48391"},
                    {"text": "Open", "callback_data": "open:48391"},
                ]
            ]
        }

        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123/sendMessage",
                json={
                    "chat_id": 42,
                    "text": "Choose",
                    "reply_markup": reply_markup,
                },
            ) as response:
                response.raise_for_status()

            await client.click(session, button_text="Open")

            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                response.raise_for_status()
                updates = (await response.json())["result"]

        self.assertEqual(updates[-1]["callback_query"]["data"], "open:48391")


class ClickActionTests(unittest.TestCase):
    def test_accepts_each_dynamic_selector(self) -> None:
        regex = ClickAction.from_payload({"callback_data_regex": r"^record:\d+$"})
        text = ClickAction.from_payload({"button_text": "Open"})

        self.assertEqual(regex.callback_data_regex, r"^record:\d+$")
        self.assertEqual(text.button_text, "Open")

    def test_rejects_missing_or_competing_selectors(self) -> None:
        with self.assertRaisesRegex(ScenarioError, "exactly one"):
            ClickAction.from_payload({})
        with self.assertRaisesRegex(ScenarioError, "exactly one"):
            ClickAction.from_payload({"callback_data": "open:1", "button_text": "Open"})

    def test_rejects_invalid_callback_regex(self) -> None:
        with self.assertRaisesRegex(ScenarioError, "regex is invalid"):
            ClickAction.from_payload({"callback_data_regex": "["})


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
