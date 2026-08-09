from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from testgram.commands.run import BotProcess
from testgram.config import BotConfig, ProjectConfig
from testgram.scenario import ScenarioError


class BotProcessDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_exited_bot_reports_stdout_and_stderr_tails(self) -> None:
        script = (
            "import sys; "
            "print('stdout marker', flush=True); "
            "print('stderr marker', file=sys.stderr, flush=True); "
            "raise SystemExit(3)"
        )
        command = f'{sys.executable} -c "{script}"'
        bot = BotProcess(
            config=ProjectConfig(bot=BotConfig(command=command)),
            server_url="http://127.0.0.1:1",
            enabled=True,
        )

        with self.assertRaises(ScenarioError) as raised:
            await bot.start()

        message = str(raised.exception)
        self.assertIn("bot stdout (tail):", message)
        self.assertIn("stdout marker", message)
        self.assertIn("bot stderr (tail):", message)
        self.assertIn("stderr marker", message)

    async def test_starts_fresh_bot_when_same_command_is_already_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            output_path = project_dir / "urls.txt"
            config_path = project_dir / "testgram.yaml"
            config_path.touch()
            script = (
                "import os, pathlib, time; "
                f"path = pathlib.Path({str(output_path)!r}); "
                "path.open('a').write(os.environ['API_SERVER_URL'] + '\\n'); "
                "time.sleep(30)"
            )
            command = f"exec {shlex.quote(sys.executable)} -c {shlex.quote(script)}"
            existing_env = os.environ.copy()
            existing_env["API_SERVER_URL"] = "http://existing.invalid"
            existing = subprocess.Popen(
                command,
                cwd=project_dir,
                env=existing_env,
                shell=True,
            )
            bot = BotProcess(
                config=ProjectConfig(
                    path=config_path,
                    bot=BotConfig(command=command),
                ),
                server_url="http://127.0.0.1:4321",
                enabled=True,
            )

            try:
                for _ in range(50):
                    if output_path.exists():
                        break
                    await asyncio.sleep(0.02)
                await bot.start()

                urls = output_path.read_text().splitlines()
                self.assertEqual(
                    urls,
                    ["http://existing.invalid", "http://127.0.0.1:4321"],
                )
            finally:
                await bot.stop()
                existing.terminate()
                existing.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
