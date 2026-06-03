from __future__ import annotations

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

        return cls(
            name=str(payload.get("name", path.stem)),
            steps=[
                ScenarioStep(payload=dict(step), line=source_line(step))
                for step in payload["steps"]
            ],
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
        print(f"scenario: {self._scenario.name}")

        for step_number, step in enumerate(self._scenario.steps, start=1):
            step_payload = step.payload
            if "message" in step_payload:
                text = str(step_payload["message"])
                print(f"{step_number}. me: {text}")
                await self._client.send_message(session, text)
                continue

            if "expect" in step_payload:
                expectation = Expectation.from_payload(
                    step_payload["expect"], self._scenario.timeout
                )
                events, seen_events = await self._client.wait_for_bot_events(
                    session=session,
                    seen_events=seen_events,
                    timeout=expectation.timeout,
                )
                match = expectation.find_match(events)
                if match is None:
                    raise ScenarioError(
                        f"{step_number}. expectation failed: {expectation.describe()}",
                        path=self._scenario.path,
                        line=step.line,
                    )
                print(f"{step_number}. bot: {self._client.format_bot_reply(match)}")
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
