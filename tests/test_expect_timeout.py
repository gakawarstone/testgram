from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from aiohttp import ClientSession, web

from testgram.client import TestgramClient
from testgram.scenario.errors import ScenarioError
from testgram.scenario.expectations import Expectation
from testgram.scenario.models import Scenario, ScenarioStep
from testgram.scenario.runner import ScenarioRunner


def message(text: str) -> dict:
    return {
        "type": "bot_api_request",
        "payload": {
            "method": "sendMessage",
            "payload": {"chat_id": 42, "text": text},
        },
    }


class ExpectTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.events = []
        self.response_delay = 0.0
        app = web.Application()
        app.router.add_get("/testgram/events", self.get_events)
        self.server = web.AppRunner(app)
        await self.server.setup()
        site = web.TCPSite(self.server, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.client = TestgramClient(f"http://127.0.0.1:{port}", chat_id=42)
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.server.cleanup()

    async def get_events(self, request: web.Request) -> web.Response:
        if self.response_delay:
            await asyncio.sleep(self.response_delay)
        return web.json_response({"result": self.events})

    async def test_runner_times_out_before_late_message(self) -> None:
        scenario = Scenario(
            name="late message",
            steps=[ScenarioStep({"expect": {"text": "late", "timeout": 0.02}}, 1)],
            timeout=1,
            path=Path("scenario.yaml"),
        )

        async def send_late() -> None:
            await asyncio.sleep(0.08)
            self.events.append(message("late"))

        task = asyncio.create_task(send_late())
        try:
            start = asyncio.get_running_loop().time()
            with self.assertRaisesRegex(ScenarioError, "expectation failed"):
                await ScenarioRunner(self.client, scenario, reset=False).run(self.session)
            self.assertLess(asyncio.get_running_loop().time() - start, 0.15)
            await task
        finally:
            task.cancel()

    async def test_delayed_http_response_cannot_succeed_after_deadline(self) -> None:
        self.events.append(message("ready"))
        self.response_delay = 0.08
        expectation = Expectation.from_payload({"text": "ready", "timeout": 0.02}, 1)
        start = asyncio.get_running_loop().time()
        result = await expectation.wait_for_match(self.client, self.session, 0)
        self.assertIsNone(result)
        self.assertLess(asyncio.get_running_loop().time() - start, 0.15)

    async def test_accumulated_unseen_messages_and_order(self) -> None:
        self.events.extend([message("already seen"), message("first"), message("second")])
        expectation = Expectation.from_payload(
            {"text": "second", "order": 2, "timeout": 0.5}, 1
        )
        result = await expectation.wait_for_match(self.client, self.session, 1)
        self.assertEqual(result, (2, self.events[2]))

    async def test_unmatched_events_are_retained_across_polls(self) -> None:
        self.events.append(message("first"))
        expectation = Expectation.from_payload(
            {"text": "second", "order": 2, "timeout": 0.8}, 1
        )

        async def send_second() -> None:
            await asyncio.sleep(0.03)
            self.events.append(message("second"))

        task = asyncio.create_task(send_second())
        try:
            result = await expectation.wait_for_match(self.client, self.session, 0)
            self.assertEqual(result, (1, self.events[1]))
        finally:
            await task

    async def test_short_window_ends_without_full_poll_interval(self) -> None:
        expectation = Expectation.from_payload({"text": "absent", "timeout": 0.02}, 1)
        start = asyncio.get_running_loop().time()
        result = await expectation.wait_for_match(self.client, self.session, 0)
        self.assertIsNone(result)
        self.assertLess(asyncio.get_running_loop().time() - start, 0.15)

    async def test_nonpositive_timeout_does_not_accept_a_message(self) -> None:
        self.events.append(message("ready"))
        for timeout in (0, -1):
            with self.subTest(timeout=timeout):
                expectation = Expectation.from_payload(
                    {"text": "ready", "timeout": timeout}, 1
                )
                self.assertIsNone(
                    await expectation.wait_for_match(self.client, self.session, 0)
                )
