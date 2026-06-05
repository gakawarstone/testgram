from __future__ import annotations

from aiohttp import ClientSession

from testgram.client import TestgramClient

from .actions import SendAction
from .errors import ScenarioError, require_mapping
from .expectations import ChatExpectation, Expectation
from .models import Scenario


class ScenarioRunner:
    def __init__(self, client: TestgramClient, scenario: Scenario, reset: bool) -> None:
        self._client = client
        self._scenario = scenario
        self._reset = reset

    async def run(self, session: ClientSession) -> None:
        if self._reset:
            await self._client.reset(session)

        seen_events = len(await self._client.get_events(session))
        scenario_start_events = seen_events
        print(f"scenario: {self._scenario.name}")

        for step_number, step in enumerate(self._scenario.steps, start=1):
            step_payload = step.payload
            if "send" in step_payload:
                send = SendAction.from_payload(
                    require_mapping(
                        step_payload["send"],
                        "send",
                        self._scenario.path,
                        step.line,
                    )
                )
                print(f"{step_number}. me: {send.describe()}")
                await send.run(client=self._client, session=session)
                continue

            if "expect" in step_payload:
                expectation = Expectation.from_payload(
                    require_mapping(
                        step_payload["expect"],
                        "expect",
                        self._scenario.path,
                        step.line,
                    ),
                    self._scenario.timeout,
                )
                indexed_events, seen_events = await self._client.wait_for_bot_events(
                    session=session,
                    seen_events=seen_events,
                    timeout=expectation.timeout,
                )
                events = [event for _, event in indexed_events]
                match = expectation.find_match(events)
                if match is None:
                    raise ScenarioError(
                        f"{step_number}. expectation failed: {expectation.describe()}",
                        path=self._scenario.path,
                        line=step.line,
                    )
                seen_events = indexed_events[events.index(match)][0] + 1
                print(f"{step_number}. bot: {self._client.format_bot_reply(match)}")
                continue

            if "expect_chat" in step_payload:
                expectation = ChatExpectation.from_payload(
                    require_mapping(
                        step_payload["expect_chat"],
                        "expect_chat",
                        self._scenario.path,
                        step.line,
                    ),
                    self._scenario.timeout,
                )
                events = await expectation.wait_for_match(
                    client=self._client,
                    session=session,
                    scenario_start_events=scenario_start_events,
                )
                print(f"{step_number}. chat: {expectation.describe(self._client, events)}")
                continue

            raise ScenarioError(
                f"{step_number}. unknown step: {step_payload}",
                path=self._scenario.path,
                line=step.line,
            )

        print("scenario passed")


async def run_scenario(client: TestgramClient, scenario: Scenario, reset: bool) -> None:
    runner = ScenarioRunner(client=client, scenario=scenario, reset=reset)

    async with ClientSession() as session:
        await runner.run(session)
