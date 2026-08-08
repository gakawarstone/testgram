from __future__ import annotations

import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
