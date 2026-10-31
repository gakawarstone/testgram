from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.scenario.errors import ScenarioError
from testgram.scenario.models import Scenario, ScenarioStep
from testgram.scenario.runner import ScenarioRunner
from testgram.server import start_server


class ActionLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.log = Path(self.directory.name) / "events.jsonl"
        self.server = await start_server("127.0.0.1", 0, self.log, quiet=True)
        self.client = TestgramClient(self.server.url, chat_id=42)
        self.session = ClientSession()
        self.runner = ScenarioRunner(
            self.client, Scenario("latency", [], 2, Path("scenario.yaml")), reset=False
        )
        self.a = (
            await self.call(
                "sendMessage",
                {
                    "chat_id": 42,
                    "text": "A",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "Убрать", "callback_data": "remove"}]
                        ]
                    },
                },
            )
        )["result"]
        self.b = (
            await self.call(
                "sendMessage",
                {
                    "chat_id": 42,
                    "text": "B",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "Убрать", "callback_data": "remove"}]
                        ]
                    },
                },
            )
        )["result"]

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.server.close()
        self.directory.cleanup()

    async def call(self, method: str, payload: dict) -> dict:
        async with self.session.post(
            f"{self.server.url}/bot123/{method}", json=payload
        ) as response:
            return await response.json()

    async def step(self, payload: dict, seen: int = 0) -> int:
        return await self.runner._run_step(
            self.session, 1, ScenarioStep(payload, 9), seen, 0
        )

    def click(self, wait_consumed: bool = False) -> dict:
        return {
            "click": {
                "name": "remove_a",
                "button_text": "Убрать",
                "message": {"text": "A"},
                "wait_consumed": wait_consumed,
            }
        }

    def expectation(
        self, within: float = 1, timeout: float = 0, **extra: object
    ) -> dict:
        return {
            "expect_api": {
                "after": "remove_a",
                "method": "deleteMessage",
                "params": {
                    "chat_id": "${actions.remove_a.chat_id}",
                    "message_id": "${actions.remove_a.message_id}",
                },
                "response": {"ok": True, "result": True},
                "latency": {"from": "remove_a", "within": within},
                "timeout": timeout,
                **extra,
            }
        }

    async def test_only_timely_matching_request_after_callback_succeeds(self) -> None:
        params = {"chat_id": 42, "message_id": self.a["message_id"]}
        await self.call("deleteMessage", params)
        seen = await self.step(self.click())
        await self.call(
            "deleteMessage", {"chat_id": 43, "message_id": self.a["message_id"]}
        )
        await self.call(
            "deleteMessage", {"chat_id": 42, "message_id": self.b["message_id"]}
        )
        await self.call("unsupported", params)
        for expectation in (self.expectation(), self.expectation(method="unsupported")):
            with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
                await self.step(expectation, seen)
        await self.call("deleteMessage", params)
        self.assertEqual(await self.step(self.expectation(), seen), seen)
        action = self.runner._actions["remove_a"]
        events = await self.client.get_events(self.session)
        request = next(
            e["payload"]
            for e in events
            if e["type"] == "bot_api_request"
            and e["payload"]["method"] == "deleteMessage"
            and e["payload"]["sequence"] > action.boundary
            and e["payload"]["payload"] == params
        )
        self.assertLessEqual(action.queued_monotonic, request["received_monotonic"])
        self.assertLessEqual(
            request["received_monotonic"], request["completed_monotonic"]
        )
        self.assertEqual(action.server_id, request["server_id"])
        log = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertTrue(all(event["time"].endswith("+00:00") for event in log))
        callback = next(event for event in log if event["type"] == "callback_query")
        self.assertEqual(callback["metadata"]["server_id"], action.server_id)
        self.assertEqual(
            callback["metadata"]["queued_monotonic"], action.queued_monotonic
        )

    async def test_late_request_does_not_pass_even_with_long_response_timeout(
        self,
    ) -> None:
        await self.step(self.click())
        await asyncio.sleep(0.12)
        await self.call(
            "deleteMessage", {"chat_id": 42, "message_id": self.a["message_id"]}
        )
        with self.assertRaisesRegex(ScenarioError, "latency from 'remove_a'"):
            await self.step(self.expectation(within=0.04, timeout=0.1))

    async def test_effect_during_wait_consumed_preserves_message_expectations(
        self,
    ) -> None:
        async def bot() -> None:
            update = (await self.call("getUpdates", {"timeout": 2}))["result"][-1]
            self.assertEqual(
                update["callback_query"]["message"]["message_id"], self.a["message_id"]
            )
            await self.call(
                "deleteMessage", {"chat_id": 42, "message_id": self.a["message_id"]}
            )
            await self.call("sendMessage", {"chat_id": 42, "text": "done"})
            await self.call("sendMessage", {"chat_id": 42, "text": "later"})
            await asyncio.sleep(0.35)
            await self.call("getUpdates", {"offset": update["update_id"] + 1})

        task = asyncio.create_task(bot())
        try:
            await self.client.wait_for_polling(self.session, timeout=1)
            seen = await self.step(self.click(wait_consumed=True), seen=2)
            seen = await self.step(self.expectation(within=0.25), seen)
            seen = await self.step({"expect": {"text": "done", "order": 1}}, seen)
            await self.step({"expect": {"text": "later", "order": 1}}, seen)
            await self.step(
                {"expect_chat": {"bot_messages": {"count": 4}, "timeout": 1}}, seen
            )
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_timely_receipt_and_delayed_completion_of_same_request(self) -> None:
        await self.step(self.click())
        action = self.runner._actions["remove_a"]
        count = await self.client.get_polling_count(self.session)
        task = asyncio.create_task(
            self.call(
                "getUpdates",
                {
                    "offset": action.update_id + 1,
                    "timeout": 1,
                },
            )
        )
        try:
            await self.client.wait_for_polling(self.session, timeout=1, after=count)
            check = self.expectation(
                within=0.5,
                timeout=0.1,
                method="getUpdates",
                params={"offset": action.update_id + 1},
                response={"ok": True, "result": []},
            )
            with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
                await self.step(check)
            check["expect_api"]["timeout"] = 2
            await self.step(check)
            await task
            events = await self.client.get_events(self.session)
            call = next(
                e["payload"]
                for e in events
                if e["type"] == "bot_api_request"
                and e["payload"]["method"] == "getUpdates"
                and e["payload"]["sequence"] > action.boundary
            )
            self.assertGreater(
                call["completed_monotonic"] - action.queued_monotonic, 0.5
            )
            self.assertLess(call["received_monotonic"] - action.queued_monotonic, 0.5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_other_server_identity_never_matches(self) -> None:
        await self.step(self.click())
        await self.call(
            "deleteMessage", {"chat_id": 42, "message_id": self.a["message_id"]}
        )
        action = self.runner._actions["remove_a"]
        self.runner._actions["remove_a"] = replace(action, server_id="other server")
        with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
            await self.step(self.expectation())
        # Also protect latency-only assertions, without an explicit after clause.
        with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
            await self.step(self.expectation(after=None))

    async def test_invalid_latency_is_reported_with_location(self) -> None:
        for latency in (
            None,
            [],
            {},
            {"from": "missing", "within": 1},
            {"from": "x", "within": -1},
            {"from": "x", "within": True},
            {"from": "x", "within": float("nan")},
            {"from": "x", "within": float("inf")},
        ):
            with (
                self.subTest(latency=latency),
                self.assertRaisesRegex(ScenarioError, "scenario.yaml:9"),
            ):
                await self.step({"expect_api": {"method": "getMe", "latency": latency}})
