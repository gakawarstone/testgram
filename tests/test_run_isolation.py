from __future__ import annotations

import argparse
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from testgram.commands.run import run_command
from testgram.scenario import ScenarioError


def run_args(scenario: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "scenario": scenario,
        "config": None,
        "host": "127.0.0.1",
        "port": 0,
        "log_file": None,
        "no_bot": False,
        "chat_id": 10,
        "username": "test_user",
        "first_name": "Test",
        "timeout": 1.0,
        "no_reset": False,
        "parallel": 1,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class DirectoryRunIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_starts_a_fresh_bot_and_server_for_each_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            scenarios = project / "scenarios"
            scenarios.mkdir()
            (scenarios / "one.yaml").write_text("name: one\nsteps: []\n")
            (scenarios / "two.yaml").write_text("name: two\nsteps: []\n")

            urls_path = project / "urls.txt"
            script = (
                "import os, pathlib, time; "
                f"path = pathlib.Path({str(urls_path)!r}); "
                "path.open('a').write(os.environ['API_SERVER_URL'] + '\\n'); "
                "time.sleep(30)"
            )
            command = f"exec {shlex.quote(sys.executable)} -c {shlex.quote(script)}"
            (project / "testgram.yaml").write_text(
                f"bot:\n  command: {json.dumps(command)}\n"
            )

            await run_command(run_args(scenarios))

            urls = urls_path.read_text().splitlines()
            self.assertEqual(len(urls), 2)
            self.assertEqual(len(set(urls)), 2)

    async def test_uses_a_distinct_chat_for_each_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            scenarios = project / "scenarios"
            scenarios.mkdir()
            (scenarios / "one.yaml").write_text(
                "name: one\nsteps:\n  - send:\n      text: first\n"
            )
            (scenarios / "two.yaml").write_text(
                "name: two\nsteps:\n  - send:\n      text: second\n"
            )
            log_path = project / "events.jsonl"

            await run_command(
                run_args(scenarios, no_bot=True, log_file=log_path, chat_id=40)
            )

            events = [json.loads(line) for line in log_path.read_text().splitlines()]
            chat_ids = [
                event["payload"]["message"]["chat"]["id"]
                for event in events
                if event["type"] == "user_message"
            ]
            self.assertEqual(chat_ids, [40, 41])

    async def test_parallel_isolation_rejects_a_shared_fixed_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scenarios = Path(directory) / "scenarios"
            scenarios.mkdir()
            (scenarios / "one.yaml").write_text("name: one\nsteps: []\n")
            (scenarios / "two.yaml").write_text("name: two\nsteps: []\n")

            with self.assertRaisesRegex(
                ScenarioError,
                "--port must be 0 when running multiple scenarios in parallel",
            ):
                await run_command(run_args(scenarios, parallel=2, port=8081))


if __name__ == "__main__":
    unittest.main()
