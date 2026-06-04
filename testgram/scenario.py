from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
import yaml

from .client import TestgramClient


@dataclass(slots=True)
class Scenario:
    name: str
    steps: list[ScenarioStep]
    timeout: float
    path: Path

    @classmethod
    def from_file(cls, path: Path, default_timeout: float) -> Scenario:
        with path.open(encoding="utf-8") as scenario_file:
            if path.suffix.lower() in {".yaml", ".yml"}:
                payload = yaml.load(scenario_file, Loader=SourceLineLoader)
            else:
                payload = json.load(scenario_file)

        if not isinstance(payload, dict):
            raise ScenarioError("expected a scenario mapping", path=path)

        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            raise ScenarioError("steps must be a list", path=path)

        steps = []
        for index, step in enumerate(raw_steps, start=1):
            if not isinstance(step, dict):
                raise ScenarioError(
                    f"{index}. step must be a mapping",
                    path=path,
                    line=source_line(step),
                )
            steps.append(ScenarioStep(payload=dict(step), line=source_line(step)))

        return cls(
            name=str(payload.get("name", path.stem)),
            steps=steps,
            timeout=float(payload.get("timeout", default_timeout)),
            path=path,
        )


@dataclass(slots=True)
class ScenarioStep:
    payload: dict[str, Any]
    line: int | None


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


@dataclass(slots=True)
class Expectation:
    method: str | None
    text: str | None
    text_contains: str | None
    timeout: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any], default_timeout: float) -> Expectation:
        return cls(
            method=optional_str(payload.get("method")),
            text=optional_str(payload.get("text")),
            text_contains=optional_str(payload.get("text_contains")),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    def find_match(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        for event in events:
            if self.matches(event):
                return event
        return None

    def matches(self, event: dict[str, Any]) -> bool:
        payload = event.get("payload", {})
        request_payload = payload.get("payload", {})

        if self.method is not None and payload.get("method") != self.method:
            return False

        text = request_payload.get("text") or request_payload.get("caption") or ""
        if self.text is not None and text != self.text:
            return False
        if self.text_contains is not None and self.text_contains not in text:
            return False

        return True

    def describe(self) -> str:
        parts = []
        if self.method is not None:
            parts.append(f"method={self.method}")
        if self.text is not None:
            parts.append(f"text={self.text!r}")
        if self.text_contains is not None:
            parts.append(f"text_contains={self.text_contains!r}")
        return ", ".join(parts) or "any bot message"


@dataclass(slots=True)
class SendAction:
    text: str
    times: int
    mode: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SendAction:
        if "text" not in payload:
            raise ScenarioError("send.text is required")

        times = int(payload.get("times", 1))
        if times < 1:
            raise ScenarioError("send.times must be at least 1")

        mode = str(payload.get("mode", "sequential"))
        if mode not in {"sequential", "concurrent"}:
            raise ScenarioError("send.mode must be 'sequential' or 'concurrent'")

        return cls(
            text=str(payload["text"]),
            times=times,
            mode=mode,
        )

    async def run(self, client: TestgramClient, session: ClientSession) -> None:
        if self.mode == "concurrent":
            await asyncio.gather(
                *(client.send_message(session, self.text) for _ in range(self.times))
            )
            return

        for _ in range(self.times):
            await client.send_message(session, self.text)

    def describe(self) -> str:
        if self.times == 1:
            return self.text
        return f"{self.text} ({self.times} times, {self.mode})"


@dataclass(slots=True)
class ChatExpectation:
    bot_messages: ChatBotMessagesExpectation | None
    no_errors: bool
    timeout: float

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        default_timeout: float,
    ) -> ChatExpectation:
        bot_messages = None
        if "bot_messages" in payload:
            if not isinstance(payload["bot_messages"], dict):
                raise ScenarioError("expect_chat.bot_messages must be a mapping")
            bot_messages = ChatBotMessagesExpectation.from_payload(
                payload["bot_messages"]
            )

        return cls(
            bot_messages=bot_messages,
            no_errors=bool(payload.get("no_errors", False)),
            timeout=float(payload.get("timeout", default_timeout)),
        )

    async def wait_for_match(
        self,
        client: TestgramClient,
        session: ClientSession,
        scenario_start_events: int,
    ) -> list[dict[str, Any]]:
        deadline = asyncio.get_running_loop().time() + self.timeout
        events: list[dict[str, Any]] = []

        while asyncio.get_running_loop().time() < deadline:
            events = (await client.get_events(session))[scenario_start_events:]
            if self.matches(client=client, events=events):
                return events
            await asyncio.sleep(0.2)

        events = (await client.get_events(session))[scenario_start_events:]
        if self.matches(client=client, events=events):
            return events

        raise ScenarioError(f"expect_chat failed: {self.failure_reason(client, events)}")

    def matches(self, client: TestgramClient, events: list[dict[str, Any]]) -> bool:
        if self.no_errors and has_error_event(events):
            return False

        if self.bot_messages is not None and not self.bot_messages.matches(
            client=client,
            events=events,
        ):
            return False

        return True

    def failure_reason(self, client: TestgramClient, events: list[dict[str, Any]]) -> str:
        reasons = []
        if self.no_errors and has_error_event(events):
            reasons.append("found error event")
        if self.bot_messages is not None:
            reason = self.bot_messages.failure_reason(client=client, events=events)
            if reason is not None:
                reasons.append(reason)
        return ", ".join(reasons) or "chat did not match"

    def describe(self, client: TestgramClient, events: list[dict[str, Any]]) -> str:
        if self.bot_messages is None:
            bot_count = sum(
                1 for event in events if event.get("type") == "bot_api_request"
            )
        else:
            bot_count = len(
                self.bot_messages.matching_messages(
                    client=client,
                    events=events,
                )
            )
        return f"{bot_count} bot API request(s) matched"


@dataclass(slots=True)
class ChatBotMessagesExpectation:
    count: int | None
    method: str | None
    text: str | None
    text_contains: str | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ChatBotMessagesExpectation:
        count = payload.get("count")
        return cls(
            count=int(count) if count is not None else None,
            method=optional_str(payload.get("method")),
            text=optional_str(payload.get("text")),
            text_contains=optional_str(payload.get("text_contains")),
        )

    def matches(self, client: TestgramClient, events: list[dict[str, Any]]) -> bool:
        messages = self.matching_messages(client=client, events=events)
        if self.count is not None and len(messages) != self.count:
            return False
        return True

    def failure_reason(
        self,
        client: TestgramClient,
        events: list[dict[str, Any]],
    ) -> str | None:
        messages = self.matching_messages(client=client, events=events)
        if self.count is not None and len(messages) != self.count:
            return f"expected {self.count} bot message(s), found {len(messages)}"
        return None

    def matching_messages(
        self,
        client: TestgramClient,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in events
            if client.is_bot_reply(event) and self.matches_filters(event)
        ]

    def matches_filters(self, event: dict[str, Any]) -> bool:
        payload = event.get("payload", {})
        request_payload = payload.get("payload", {})

        if self.method is not None and payload.get("method") != self.method:
            return False

        text = request_payload.get("text") or request_payload.get("caption") or ""
        if self.text is not None and text != self.text:
            return False
        if self.text_contains is not None and self.text_contains not in text:
            return False

        return True


def has_error_event(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if "error" in str(event.get("type", "")).lower():
            return True

        payload = event.get("payload", {})
        response = payload.get("response", {})
        if isinstance(response, dict) and response.get("ok") is False:
            return True

    return False


class ScenarioError(Exception):
    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        line: int | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.line = line
        super().__init__(message)

    def __str__(self) -> str:
        if self.path is None:
            return self.message
        if self.line is None:
            return f"{self.path}: {self.message}"
        return f"{self.path}:{self.line}: {self.message}"


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def require_mapping(
    value: Any,
    name: str,
    path: Path | None,
    line: int | None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{name} must be a mapping", path=path, line=line)
    return value


class SourceMapping(dict[str, Any]):
    def __init__(self, *args: Any, line: int | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.line = line


class SourceLineLoader(yaml.SafeLoader):
    pass


def construct_source_mapping(
    loader: SourceLineLoader,
    node: yaml.nodes.MappingNode,
) -> SourceMapping:
    loader.flatten_mapping(node)
    return SourceMapping(
        loader.construct_pairs(node),
        line=node.start_mark.line + 1,
    )


SourceLineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_source_mapping,
)


def source_line(value: Any) -> int | None:
    return value.line if isinstance(value, SourceMapping) else None
