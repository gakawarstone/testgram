from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.scenario.errors import ScenarioError
from testgram.scenario.models import Scenario, ScenarioStep
from testgram.scenario.runner import ScenarioRunner
from testgram.server import start_server


class ActionResultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = await start_server("127.0.0.1", 0, quiet=True)
        self.client = TestgramClient(self.server.url, chat_id=42)
        self.session = ClientSession()
        self.scenario = Scenario("actions", [], 1, Path("scenario.yaml"))
        self.runner = ScenarioRunner(self.client, self.scenario, reset=False)

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.server.close()

    async def call(self, method: str, payload: dict) -> dict:
        async with self.session.post(
            f"{self.server.url}/bot123/{method}", json=payload
        ) as response:
            return await response.json()

    async def messages(self) -> tuple[dict, dict]:
        results = []
        for text in ("Запись A", "Запись B"):
            response = await self.call(
                "sendMessage",
                {
                    "chat_id": 42,
                    "text": text,
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "Убрать", "callback_data": "remove"}]
                        ]
                    },
                },
            )
            results.append(response["result"])
        return results[0], results[1]

    async def step(self, payload: dict, seen: int = 0) -> int:
        return await self.runner._run_step(
            self.session, 1, ScenarioStep(payload, 9), seen, 0
        )

    def api(self, **extra: object) -> dict:
        return {
            "expect_api": {
                "after": "remove_a",
                "method": "deleteMessage",
                "params": {
                    "chat_id": "${actions.remove_a.chat_id}",
                    "message_id": "${actions.remove_a.message_id}",
                },
                "response": {"ok": True, "result": True},
                "timeout": 0,
                **extra,
            }
        }

    async def test_targets_a_and_rejects_old_or_wrong_deletions(self) -> None:
        a, b = await self.messages()
        await self.call("deleteMessage", {"chat_id": 42, "message_id": a["message_id"]})
        seen = await self.step(
            {
                "click": {
                    "name": "remove_a",
                    "button_text": "Убрать",
                    "message": {"text_contains": "Запись A"},
                    "wait_consumed": False,
                }
            }
        )
        async with self.session.post(
            f"{self.server.url}/bot123/getUpdates", json={}
        ) as response:
            callback_update = (await response.json())["result"][-1]
        callback = callback_update["callback_query"]
        self.assertEqual(callback["message"]["message_id"], a["message_id"])
        self.assertEqual(
            self.runner._actions["remove_a"].update_id, callback_update["update_id"]
        )
        with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
            await self.step(self.api(), seen)
        await self.call("deleteMessage", {"chat_id": 42, "message_id": b["message_id"]})
        await self.call("deleteMessage", {"chat_id": 43, "message_id": a["message_id"]})
        with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
            await self.step(self.api(), seen)
        await self.call("deleteMessage", {"chat_id": 42, "message_id": a["message_id"]})
        self.assertEqual(await self.step(self.api(), seen), seen)

    async def test_legacy_click_returns_source_index(self) -> None:
        await self.messages()
        self.assertEqual(await self.client.click(self.session, button_text="Убрать"), 1)

    async def test_old_request_finishing_after_callback_is_excluded(self) -> None:
        await self.messages()
        poll = asyncio.create_task(self.call("getUpdates", {"timeout": 2}))
        try:
            await self.client.wait_for_polling(self.session, timeout=1)
            await self.step(
                {
                    "click": {
                        "name": "remove_a",
                        "button_text": "Убрать",
                        "wait_consumed": False,
                    }
                }
            )
            await poll
            with self.assertRaisesRegex(ScenarioError, "expect_api failed"):
                await self.step(
                    {
                        "expect_api": {
                            "after": "remove_a",
                            "method": "getUpdates",
                            "timeout": 0,
                        }
                    }
                )
            await self.call("getUpdates", {})
            await self.step(
                {
                    "expect_api": {
                        "after": "remove_a",
                        "method": "getUpdates",
                        "timeout": 0,
                    }
                }
            )
        finally:
            if not poll.done():
                poll.cancel()
                await asyncio.gather(poll, return_exceptions=True)

    async def test_during_wait_consumed_and_message_expectations(self) -> None:
        a, _ = await self.messages()
        scenario_text = """\
name: action
steps:
  - click:
      name: remove_a
      button_text: Убрать
      message: {text_contains: Запись A}
  - expect_api:
      after: remove_a
      method: deleteMessage
      params: {chat_id: '${actions.remove_a.chat_id}', message_id: '${actions.remove_a.message_id}'}
      response: {ok: true, result: true}
      timeout: 0
  - expect: {text: done, order: 1}
  - expect: {text: later, order: 1}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.yaml"
            path.write_text(scenario_text, encoding="utf-8")
            scenario = Scenario.from_file(path, default_timeout=1)

            async def bot() -> None:
                updates = (await self.call("getUpdates", {"timeout": 2}))["result"]
                update = updates[-1]
                self.assertEqual(
                    update["callback_query"]["message"]["message_id"], a["message_id"]
                )
                await self.call(
                    "deleteMessage", {"chat_id": 42, "message_id": a["message_id"]}
                )
                await self.call("sendMessage", {"chat_id": 42, "text": "done"})
                await self.call("sendMessage", {"chat_id": 42, "text": "later"})
                await self.call("getUpdates", {"offset": update["update_id"] + 1})

            task = asyncio.create_task(bot())
            try:
                await self.client.wait_for_polling(self.session, timeout=1)
                await ScenarioRunner(self.client, scenario, reset=False).run(
                    self.session
                )
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_invalid_names_and_references_fail_with_location(self) -> None:
        await self.messages()
        for payload in (
            {"click": {"name": "bad.name", "button_text": "Убрать"}},
            {"expect_api": {"after": "missing", "method": "getMe"}},
            {
                "expect_api": {
                    "method": "getMe",
                    "params": {"x": "${actions.missing.chat_id}"},
                }
            },
            {
                "expect_api": {
                    "method": "getMe",
                    "params": {"x": "${actions.a.boundary}"},
                }
            },
            {
                "expect_api": {
                    "method": "getMe",
                    "response": {"x": "x${actions.a.chat_id}"},
                }
            },
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaisesRegex(ScenarioError, "scenario.yaml:9"),
            ):
                await self.step(payload)
        click = {
            "click": {
                "name": "remove_a",
                "button_text": "Убрать",
                "wait_consumed": False,
            }
        }
        await self.step(click)
        updates_before = await self.call("getUpdates", {})
        with self.assertRaisesRegex(ScenarioError, "duplicate action name"):
            await self.step(click)
        self.assertEqual(updates_before, await self.call("getUpdates", {}))

    async def test_references_preserve_numeric_type_in_nested_response(self) -> None:
        await self.messages()
        await self.step(
            {
                "click": {
                    "name": "remove_a",
                    "button_text": "Убрать",
                    "wait_consumed": False,
                }
            }
        )
        await self.call("sendMessage", {"chat_id": 42, "text": "after"})
        await self.step(
            {
                "expect_api": {
                    "after": "remove_a",
                    "method": "sendMessage",
                    "timeout": 0,
                    "response": {
                        "result": {"chat": {"id": "${actions.remove_a.chat_id}"}}
                    },
                }
            }
        )
        await self.call("getUpdates", {})
        await self.step(
            {
                "expect_api": {
                    "after": "remove_a",
                    "method": "getUpdates",
                    "timeout": 0,
                    "response": {
                        "result": [{"update_id": "${actions.remove_a.update_id}"}]
                    },
                }
            }
        )
