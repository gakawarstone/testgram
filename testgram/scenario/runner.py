from __future__ import annotations

import re
from typing import Any

from aiohttp import ClientSession

from testgram.client import ClickResult, TestgramClient

from .actions import ClickAction, InlineQueryAction, SendAction, UpdateAction
from .errors import ScenarioError, require_mapping
from .expectations import ApiExpectation, ChatExpectation, Expectation, NoneExpectation
from .models import Scenario, ScenarioStep


class ScenarioRunner:
    def __init__(self, client: TestgramClient, scenario: Scenario, reset: bool) -> None:
        self._client = client
        self._scenario = scenario
        self._reset = reset
        self._actions: dict[str, ClickResult] = {}

    async def run(self, session: ClientSession) -> None:
        self._actions.clear()
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
                ),
                self._scenario.timeout,
            )
            print(f"{step_number}. me: {send.describe()}")
            try:
                await send.run(client=self._client, session=session)
            except TimeoutError as error:
                raise ScenarioError(
                    f"{step_number}. send failed: {error}",
                    path=self._scenario.path,
                    line=step.line,
                ) from error
            return seen_events

        if "click" in step_payload:
            click_payload = require_mapping(
                step_payload["click"], "click", self._scenario.path, step.line
            )
            name = click_payload.get("name")
            if name is not None and (
                not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) is None
            ):
                raise ScenarioError(
                    "click.name must be an identifier",
                    path=self._scenario.path,
                    line=step.line,
                )
            if name is not None and name in self._actions:
                raise ScenarioError(
                    f"duplicate action name: {name}",
                    path=self._scenario.path,
                    line=step.line,
                )
            click = ClickAction.from_payload(
                click_payload,
                self._scenario.timeout,
            )
            print(f"{step_number}. me: click {click.describe()}")
            try:
                result = await click.run_with_result(client=self._client, session=session)
            except (ScenarioError, TimeoutError) as error:
                raise ScenarioError(
                    f"{step_number}. click failed: {error}",
                    path=self._scenario.path,
                    line=step.line,
                ) from error
            if name is not None:
                self._actions[name] = result
            return max(seen_events, result.source_event + 1)

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

        if "expect_api" in step_payload:
            payload = require_mapping(
                step_payload["expect_api"], "expect_api", self._scenario.path, step.line
            )
            try:
                after = payload.get("after")
                if after is not None and (
                    not isinstance(after, str) or after not in self._actions
                ):
                    raise ScenarioError(f"unknown action in expect_api.after: {after!r}")
                resolved = dict(payload)
                for key in ("params", "response"):
                    if key in resolved:
                        resolved[key] = self._resolve_action_values(resolved[key])
                expectation = ApiExpectation.from_payload(
                    resolved, self._scenario.timeout
                )
            except ScenarioError as error:
                raise ScenarioError(
                    f"{step_number}. {error}", path=self._scenario.path, line=step.line
                ) from error
            match = await expectation.wait_for_match(
                client=self._client,
                session=session,
                scenario_start_events=scenario_start_events,
                after_boundary=(
                    self._actions[after].boundary if after is not None else None
                ),
            )
            if match is None:
                raise ScenarioError(
                    f"{step_number}. expect_api failed: {expectation.describe()}",
                    path=self._scenario.path,
                    line=step.line,
                )
            print(f"{step_number}. api: {expectation.describe()}")
            return seen_events

        if "expect_none" in step_payload:
            expectation = NoneExpectation.from_payload(
                require_mapping(
                    step_payload["expect_none"],
                    "expect_none",
                    self._scenario.path,
                    step.line,
                ),
                self._scenario.timeout,
            )
            violation, final_seen_events = await expectation.observe(
                client=self._client,
                session=session,
                seen_events=seen_events,
            )
            if violation is not None:
                _, event = violation
                raise ScenarioError(
                    f"{step_number}. expect_none failed: got "
                    f"{self._client.format_bot_reply(event)}; "
                    f"forbidden {expectation.describe()}",
                    path=self._scenario.path,
                    line=step.line,
                )
            print(f"{step_number}. bot: no {expectation.describe()}")
            return final_seen_events

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

    def _resolve_action_values(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve_action_values(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_action_values(item) for item in value]
        if isinstance(value, str) and "${actions." in value:
            match = re.fullmatch(
                r"\$\{actions\.([A-Za-z_][A-Za-z0-9_-]*)\.(update_id|chat_id|message_id)\}",
                value,
            )
            if match is None:
                raise ScenarioError(f"invalid action reference: {value!r}")
            name, field = match.groups()
            if name not in self._actions:
                raise ScenarioError(f"unknown action in reference: {name!r}")
            return getattr(self._actions[name], field)
        return value


async def run_scenario(client: TestgramClient, scenario: Scenario, reset: bool) -> None:
    runner = ScenarioRunner(client=client, scenario=scenario, reset=reset)

    async with ClientSession() as session:
        await runner.run(session)
