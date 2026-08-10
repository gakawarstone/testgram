from __future__ import annotations

from aiohttp import ClientSession

from testgram.client import TestgramClient

from .actions import ClickAction, InlineQueryAction, SendAction, UpdateAction
from .errors import ScenarioError, require_mapping
from .expectations import ChatExpectation, Expectation
from .models import Scenario, ScenarioStep


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
            seen_events = await self._run_step(
                session=session,
                step_number=step_number,
                step=step,
                seen_events=seen_events,
                scenario_start_events=scenario_start_events,
            )

        print("scenario passed")

    async def _run_step(
        self,
        session: ClientSession,
        step_number: int,
        step: ScenarioStep,
        seen_events: int,
        scenario_start_events: int,
    ) -> int:
        step_payload = step.payload
        if "send" in step_payload:
            send = SendAction.from_payload(
                require_mapping(
                    step_payload["send"], "send", self._scenario.path, step.line
                )
            )
            print(f"{step_number}. me: {send.describe()}")
            await send.run(client=self._client, session=session)
            return seen_events

        if "click" in step_payload:
            click = ClickAction.from_payload(
                require_mapping(
                    step_payload["click"], "click", self._scenario.path, step.line
                )
            )
            print(f"{step_number}. me: click {click.describe()}")
            try:
                source_event = await click.run(client=self._client, session=session)
            except ScenarioError as error:
                raise ScenarioError(
                    f"{step_number}. click failed: {error}",
                    path=self._scenario.path,
                    line=step.line,
                ) from error
            return max(seen_events, source_event + 1)

        if "inline_query" in step_payload:
            inline_query = InlineQueryAction.from_payload(
                require_mapping(
                    step_payload["inline_query"],
                    "inline_query",
                    self._scenario.path,
                    step.line,
                )
            )
            print(f"{step_number}. me: inline query {inline_query.describe()}")
            await inline_query.run(client=self._client, session=session)
            return seen_events

        if "update" in step_payload:
            update = UpdateAction.from_payload(
                require_mapping(
                    step_payload["update"], "update", self._scenario.path, step.line
                )
            )
            print(f"{step_number}. me: update {update.describe()}")
            await update.run(client=self._client, session=session)
            return seen_events

        if "expect" in step_payload:
            expectation = Expectation.from_payload(
                require_mapping(
                    step_payload["expect"], "expect", self._scenario.path, step.line
                ),
                self._scenario.timeout,
            )
            match = await expectation.wait_for_match(
                client=self._client,
                session=session,
                seen_events=seen_events,
            )
            if match is None:
                raise ScenarioError(
                    f"{step_number}. expectation failed: {expectation.describe()}",
                    path=self._scenario.path,
                    line=step.line,
                )
            event_index, event = match
            print(f"{step_number}. bot: {self._client.format_bot_reply(event)}")
            return event_index + 1

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
            return seen_events

        raise ScenarioError(
            f"{step_number}. unknown step: {step_payload}",
            path=self._scenario.path,
            line=step.line,
        )


async def run_scenario(client: TestgramClient, scenario: Scenario, reset: bool) -> None:
    runner = ScenarioRunner(client=client, scenario=scenario, reset=reset)

    async with ClientSession() as session:
        await runner.run(session)
