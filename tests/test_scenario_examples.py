from __future__ import annotations

import unittest
from pathlib import Path

from testgram.scenario.actions import InlineQueryAction, SendAction, UpdateAction
from testgram.scenario.models import Scenario


class ScenarioExampleTests(unittest.TestCase):
    def test_examples_use_valid_action_payloads(self) -> None:
        examples = Path(__file__).parents[1] / "examples" / "scenarios"
        paths = sorted(examples.glob("*.yaml"))
        self.assertTrue(paths)

        parsers = {
            "send": SendAction.from_payload,
            "inline_query": InlineQueryAction.from_payload,
            "update": UpdateAction.from_payload,
        }
        for path in paths:
            with self.subTest(path=path.name):
                scenario = Scenario.from_file(path, default_timeout=5)
                for step in scenario.steps:
                    for action, parse in parsers.items():
                        if action in step.payload:
                            parse(step.payload[action])


if __name__ == "__main__":
    unittest.main()
