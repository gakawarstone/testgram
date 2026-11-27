from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.scenario.errors import ScenarioError
from testgram.scenario.expectations import ApiExpectation
from testgram.scenario.models import Scenario, ScenarioStep
from testgram.scenario.runner import ScenarioRunner
from testgram.server import RunningServer, start_server


class ApiExpectationTests(unittest.IsolatedAsyncioTestCase):
    server: RunningServer

    async def asyncSetUp(self) -> None:
        self.server = await start_server("127.0.0.1", 0, quiet=True)
        self.client = TestgramClient(self.server.url, chat_id=42)
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.server.close()

    async def call(self, method: str, payload: dict, *, form: bool = False) -> dict:
        kwargs = {"data" if form else "json": payload}
        async with self.session.post(
            f"{self.server.url}/bot123/{method}", **kwargs
        ) as response:
            return await response.json()

    async def test_waits_for_a_future_call_and_checks_existing_call(self) -> None:
        expectation = ApiExpectation.from_payload(
            {"method": "deleteMessage", "params": {"chat_id": 42, "message_id": 7},
             "response": {"ok": True, "result": True}, "timeout": 1}, 1
        )
        waiter = asyncio.create_task(expectation.wait_for_match(self.client, self.session, 0))
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        await self.call("deleteMessage", {"chat_id": 42, "message_id": 7}, form=True)
        first = await waiter
        self.assertIsNotNone(first)
        second = await expectation.wait_for_match(self.client, self.session, 0)
        self.assertEqual(first, second)
        self.assertIsNone(await expectation.wait_for_match(self.client, self.session, 1))

    async def test_errors_wrong_method_chat_message_and_response_do_not_match(self) -> None:
        await self.call("unsupportedMethod", {"chat_id": 42, "message_id": 7})
        await self.call("deleteMessage", {"chat_id": 43, "message_id": 7})
        await self.call("deleteMessage", {"chat_id": 42, "message_id": 8})
        for payload in (
            {"method": "unsupportedMethod", "params": {"chat_id": 42}},
            {"method": "deleteMessage", "params": {"chat_id": 42, "message_id": 7}},
            {"method": "deleteMessage", "response": {"result": False}},
            {"method": "deleteMessage", "response": {"ok": False}},
        ):
            expectation = ApiExpectation.from_payload({**payload, "timeout": 0}, 1)
            self.assertIsNone(await expectation.wait_for_match(self.client, self.session, 0))

    async def test_runner_reports_missing_call_before_it_is_recorded(self) -> None:
        scenario = Scenario(name="missing", timeout=0, path=Path("scenario.yaml"), steps=[])
        runner = ScenarioRunner(self.client, scenario, reset=False)
        step = ScenarioStep({"expect_api": {"method": "deleteMessage", "timeout": 0}}, 7)
        with self.assertRaisesRegex(ScenarioError, r"scenario.yaml:7: 1. expect_api failed"):
            await runner._run_step(self.session, 1, step, 0, 0)
        await self.call("deleteMessage", {"chat_id": 42, "message_id": 7})
        self.assertEqual(await runner._run_step(self.session, 1, step, 0, 0), 0)

    async def test_nested_response_and_arbitrary_method(self) -> None:
        await self.call("sendMessage", {"chat_id": 42, "text": "Hello"})
        events = await self.client.get_events(self.session)
        matching = ApiExpectation.from_payload(
            {"method": "sendMessage", "params": {"text": "Hello"},
             "response": {"result": {"chat": {"id": 42}, "text": "Hello"}}}, 1
        )
        self.assertTrue(matching.matches(events[0]))
        matching.response["result"]["chat"]["id"] = 43
        self.assertFalse(matching.matches(events[0]))
        await self.call("getMe", {})
        self.assertIsNotNone(await ApiExpectation.from_payload(
            {"method": "getMe", "timeout": 0}, 1
        ).wait_for_match(self.client, self.session, 0))

    async def test_scenario_keeps_message_order_and_chat_counts(self) -> None:
        scenario = Scenario(
            name="API and messages", timeout=1, path=Path("scenario.yaml"), steps=[
                ScenarioStep({"send": {"text": "go", "wait_consumed": False}}, None),
                ScenarioStep({"expect_api": {"method": "deleteMessage",
                    "params": {"chat_id": 42, "message_id": 1},
                    "response": {"result": True}}}, None),
                ScenarioStep({"expect": {"order": 1, "text": "first"}}, None),
                ScenarioStep({"expect": {"order": 1, "text": "second"}}, None),
                ScenarioStep({"expect_chat": {"bot_messages": {"count": 2,
                    "messages": [{"text": "first"}, {"text": "second"}]}}}, None),
            ]
        )

        async def bot() -> None:
            async with self.session.post(
                f"{self.server.url}/bot123/getUpdates", json={"timeout": 1}
            ) as response:
                await response.json()
            await self.call("sendMessage", {"chat_id": 42, "text": "first"})
            await self.call("deleteMessage", {"chat_id": 42, "message_id": 1})
            await self.call("sendMessage", {"chat_id": 42, "text": "second"})

        bot_task = asyncio.create_task(bot())
        try:
            await ScenarioRunner(self.client, scenario, reset=False).run(self.session)
            await bot_task
        finally:
            if not bot_task.done():
                bot_task.cancel()
                await asyncio.gather(bot_task, return_exceptions=True)

    def test_invalid_expectations(self) -> None:
        for payload in ({}, {"method": ""}, {"method": "x", "params": []},
                        {"method": "x", "response": True},
                        {"method": "x", "timeout": -1}):
            with self.subTest(payload=payload), self.assertRaises(ScenarioError):
                ApiExpectation.from_payload(payload, 1)
