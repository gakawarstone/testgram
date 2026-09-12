from __future__ import annotations

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from aiohttp import ClientSession

from testgram.chat import open_chat
from testgram.client import TestgramClient
from testgram.scenario.actions import ClickAction
from testgram.scenario.errors import ScenarioError
from testgram.scenario.expectations import (
    ChatBotMessagesExpectation,
    ChatExpectation,
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

    async def test_click_restricts_button_search_with_message_matcher(self) -> None:
        client = TestgramClient(self.server.url, chat_id=42)

        async with ClientSession() as session:
            for text, callback_data in (
                ("First record", "open:1"),
                ("Second record", "open:2"),
            ):
                async with session.post(
                    f"{self.server.url}/bot123/sendMessage",
                    json={
                        "chat_id": 42,
                        "text": text,
                        "reply_markup": {
                            "inline_keyboard": [
                                [{"text": "Open", "callback_data": callback_data}]
                            ]
                        },
                    },
                ) as response:
                    response.raise_for_status()

            action = ClickAction.from_payload(
                {
                    "button_text": "Open",
                    "message": {"text": "First record"},
                    "wait_consumed": False,
                }
            )
            await action.run(client, session)

            async with session.post(
                f"{self.server.url}/bot123/getUpdates", json={}
            ) as response:
                response.raise_for_status()
                updates = (await response.json())["result"]

        callback = updates[-1]["callback_query"]
        self.assertEqual(callback["data"], "open:1")
        self.assertEqual(callback["message"]["text"], "First record")

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


class ClickActionTests(unittest.TestCase):
    def test_accepts_each_dynamic_selector(self) -> None:
        regex = ClickAction.from_payload({"callback_data_regex": r"^record:\d+$"})
        text = ClickAction.from_payload({"button_text": "Open"})

        self.assertEqual(regex.callback_data_regex, r"^record:\d+$")
        self.assertEqual(text.button_text, "Open")

    def test_accepts_message_matcher(self) -> None:
        action = ClickAction.from_payload(
            {"button_text": "Open", "message": {"text_contains": "created"}}
        )

        self.assertIsNotNone(action.message)
        self.assertEqual(action.message.text_contains, "created")

    def test_rejects_missing_or_competing_selectors(self) -> None:
        with self.assertRaisesRegex(ScenarioError, "exactly one"):
            ClickAction.from_payload({})
        with self.assertRaisesRegex(ScenarioError, "exactly one"):
            ClickAction.from_payload({"callback_data": "open:1", "button_text": "Open"})

    def test_rejects_invalid_callback_regex(self) -> None:
        with self.assertRaisesRegex(ScenarioError, "regex is invalid"):
            ClickAction.from_payload({"callback_data_regex": "["})

    def test_rejects_non_mapping_message_matcher(self) -> None:
        with self.assertRaisesRegex(ScenarioError, "click.message must be a mapping"):
            ClickAction.from_payload({"button_text": "Open", "message": "created"})


class UnsupportedMethodTests(unittest.IsolatedAsyncioTestCase):
    server: RunningServer

    async def asyncSetUp(self) -> None:
        self.server = await start_server("127.0.0.1", 0, quiet=True)

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def test_returns_bot_api_error_and_records_failed_response(self) -> None:
        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123/unsupportedMethod",
                json={"chat_id": 42},
            ) as response:
                self.assertEqual(response.status, 404)
                payload = await response.json()

            async with session.get(f"{self.server.url}/testgram/events") as response:
                response.raise_for_status()
                events = (await response.json())["result"]

        expected_response = {
            "ok": False,
            "error_code": 404,
            "description": "Not Found",
        }
        self.assertEqual(payload, expected_response)
        self.assertEqual(events[-1]["payload"]["method"], "unsupportedMethod")
        self.assertEqual(events[-1]["payload"]["response"], expected_response)


class ReplyMarkupResponseTests(unittest.IsolatedAsyncioTestCase):
    server: RunningServer

    async def asyncSetUp(self) -> None:
        self.server = await start_server("127.0.0.1", 0, quiet=True)

    async def asyncTearDown(self) -> None:
        await self.server.close()

    async def test_reply_keyboard_is_not_returned_in_message(self) -> None:
        reply_keyboard = {
            "keyboard": [[{"text": "Books"}]],
            "resize_keyboard": True,
        }

        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123/sendMessage",
                json={
                    "chat_id": 42,
                    "text": "Choose a section",
                    "reply_markup": reply_keyboard,
                },
            ) as response:
                response.raise_for_status()
                message = (await response.json())["result"]

            events = await TestgramClient(
                self.server.url, chat_id=42
            ).get_events(session)

        self.assertNotIn("reply_markup", message)
        self.assertEqual(events[0]["payload"]["payload"]["reply_markup"], reply_keyboard)

    async def test_inline_keyboard_is_returned_in_message(self) -> None:
        inline_keyboard = {
            "inline_keyboard": [
                [{"text": "Open", "callback_data": "books:open"}]
            ]
        }

        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123/sendMessage",
                json={
                    "chat_id": 42,
                    "text": "Books",
                    "reply_markup": inline_keyboard,
                },
            ) as response:
                response.raise_for_status()
                message = (await response.json())["result"]

        self.assertEqual(message["reply_markup"], inline_keyboard)


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

    def test_forbidden_message_can_match_a_document_in_another_chat(self) -> None:
        event = {
            "type": "bot_api_request",
            "payload": {
                "method": "sendDocument",
                "payload": {
                    "chat_id": 99,
                    "document": {"filename": "crash.log", "content_type": "text/plain"},
                },
                "response": {"ok": True, "result": {}},
            },
        }

        expectation = ChatExpectation.from_payload(
            {"forbidden_bot_messages": [{"filename": "crash.log"}]},
            default_timeout=1,
        )
        client = TestgramClient("http://unused", chat_id=42)

        self.assertFalse(expectation.matches(client, [event]))
        self.assertIn(
            "found forbidden bot message",
            expectation.failure_reason(client, [event]),
        )

    def test_other_documents_are_allowed(self) -> None:
        event = {
            "type": "bot_api_request",
            "payload": {
                "method": "sendDocument",
                "payload": {
                    "chat_id": 99,
                    "document": {
                        "filename": "report.txt",
                        "content_type": "text/plain",
                    },
                },
                "response": {"ok": True, "result": {}},
            },
        }
        expectation = ChatExpectation.from_payload(
            {"forbidden_bot_messages": [{"filename": "crash.log"}]},
            default_timeout=1,
        )
        client = TestgramClient("http://unused", chat_id=42)

        self.assertTrue(expectation.matches(client, [event]))


if __name__ == "__main__":
    unittest.main()
