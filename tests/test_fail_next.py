from __future__ import annotations

import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession

from testgram.client import TestgramClient
from testgram.commands.run import run_command
from testgram.scenario import Scenario, ScenarioError, run_scenario
from testgram.server import start_server
from tests.test_run_isolation import run_args


FAIL_NEXT = """\
  - fail_next:
      method: editMessageText
      error_code: 400
      description: "Bad Request: message can't be edited"
"""

HTTP_BOT = """\
import asyncio
import os

from aiohttp import ClientSession


async def main():
    url = os.environ['API_SERVER_URL'] + '/bot123:test/'
    async with ClientSession() as session:
        async def request(method, **data):
            async with session.post(url + method, json=data) as response:
                return response.status, await response.json()

        updates = []
        while not updates:
            _, body = await request('getUpdates', timeout=1)
            updates = body['result']
        update = updates[0]
        chat_id = update['message']['chat']['id']
        code = int(update['message']['text'])

        status, body = await request('sendMessage', chat_id=chat_id, text='Form')
        assert status == 200, body
        form_id = body['result']['message_id']

        edits = await asyncio.gather(*(
            request('editMessageText', chat_id=chat_id, message_id=form_id, text='Title')
            for _ in range(2)
        ))
        assert [body for status, body in edits if status == code] == [{
            'ok': False,
            'error_code': code,
            'description': "Bad Request: message can't be edited",
        }], edits
        assert [body['ok'] for status, body in edits if status == 200] == [True], edits

        status, body = await request('sendMessage', chat_id=chat_id, text='Author?')
        assert status == 200, body
        # The failed edit must never allocate a message ID in the fake API.
        assert body['result']['message_id'] == form_id + 2, body
        await request('getUpdates', offset=update['update_id'] + 1)
        await asyncio.Event().wait()


asyncio.run(main())
"""


class FailNextProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_bots_get_one_http_error_during_concurrent_edits(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            scenarios = project / "scenarios"
            scenarios.mkdir()
            for code in (400, 403):
                (scenarios / f"{code}.yaml").write_text(
                    "steps:\n"
                    + FAIL_NEXT.replace("400", str(code))
                    + f'  - send: {{text: "{code}"}}\n'
                    + '  - expect: {method: sendMessage, text: "Author?"}\n'
                    + "  - expect_chat:\n"
                    + "      bot_messages: {method: editMessageText, count: 1}\n"
                )
            (project / "bot.py").write_text(HTTP_BOT)
            command = f"exec {shlex.quote(sys.executable)} bot.py"
            (project / "testgram.yaml").write_text(
                f"bot:\n  command: {json.dumps(command)}\n"
            )

            await run_command(run_args(scenarios, parallel=2, timeout=3.0))


class FailNextScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "failure.yaml"
        self.server = await start_server("127.0.0.1", 0, quiet=True)
        self.addAsyncCleanup(self.server.close)
        self.client = TestgramClient(self.server.url, chat_id=1)

    async def run_steps(self, steps: str) -> None:
        self.path.write_text("steps:\n" + steps)
        scenario = Scenario.from_file(self.path, default_timeout=1)
        await run_scenario(self.client, scenario, reset=False)

    async def assert_edit_succeeds(self) -> None:
        async with ClientSession() as session:
            async with session.post(
                f"{self.server.url}/bot123:test/editMessageText",
                json={"chat_id": 1, "message_id": 4, "text": "Updated"},
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())["result"]["text"], "Updated")

    async def test_unused_rule_reports_line_and_cleans_up_for_server_reuse(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ScenarioError,
            r"failure\.yaml:2: .*unused fail_next rule for editMessageText",
        ):
            await self.run_steps(FAIL_NEXT)

        await self.assert_edit_succeeds()

    async def test_cleans_up_when_another_step_fails(self) -> None:
        with self.assertRaisesRegex(ScenarioError, "unknown step"):
            await self.run_steps(FAIL_NEXT + "  - unknown: {}\n")

        await self.assert_edit_succeeds()

    async def test_invalid_yaml_identifies_the_step_and_field(self) -> None:
        cases = [
            ("[]", "fail_next must be a mapping"),
            ("{}", "fail_next.method"),
            ("{method: /editMessageText}", "fail_next.method"),
            ("{method: getMe}", "fail_next.error_code"),
            ("{method: getMe, error_code: true}", "fail_next.error_code"),
            ("{method: getMe, error_code: '400'}", "fail_next.error_code"),
            ("{method: getMe, error_code: 200}", "fail_next.error_code"),
            ("{method: getMe, error_code: 600}", "fail_next.error_code"),
            ("{method: getMe, error_code: 400}", "fail_next.description"),
            (
                "{method: getMe, error_code: 400, description: ' '}",
                "fail_next.description",
            ),
            ("{method: getMe, error_code: 400, typo: error}", "unknown field 'typo'"),
        ]
        for payload, message in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ScenarioError) as caught:
                    await self.run_steps(f"  - fail_next: {payload}\n")
                self.assertEqual(caught.exception.path, self.path)
                self.assertEqual(caught.exception.line, 2)
                self.assertIn(message, caught.exception.message)
