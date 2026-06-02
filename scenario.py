from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import ClientSession

from testgram.client import TestgramClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a testgram scenario")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--chat-id", default=1, type=int)
    parser.add_argument("--username", default="test_user")
    parser.add_argument("--first-name", default="Test")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--no-reset", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    scenario = Scenario.from_file(args.scenario, default_timeout=args.timeout)
    client = TestgramClient(
        base_url=args.url,
        chat_id=args.chat_id,
        username=args.username,
        first_name=args.first_name,
    )
    runner = ScenarioRunner(client=client, scenario=scenario, reset=not args.no_reset)

    async with ClientSession() as session:
        await runner.run(session)


@dataclass(slots=True)
class Scenario:
    name: str
    steps: list[dict[str, Any]]
    timeout: float

    @classmethod
    def from_file(cls, path: Path, default_timeout: float) -> Scenario:
        with path.open(encoding="utf-8") as scenario_file:
            payload = json.load(scenario_file)

        return cls(
            name=str(payload.get("name", path.stem)),
            steps=list(payload["steps"]),
            timeout=float(payload.get("timeout", default_timeout)),
        )


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
            if "message" in step:
                text = str(step["message"])
                print(f"{step_number}. me: {text}")
                await self._client.send_message(session, text)
                continue

            if "expect" in step:
                expectation = Expectation.from_payload(step["expect"], self._scenario.timeout)
                events, seen_events = await self._client.wait_for_bot_events(
                    session=session,
                    seen_events=seen_events,
                    timeout=expectation.timeout,
                )
                match = expectation.find_match(events)
                if match is None:
                    raise ScenarioError(
                        f"{step_number}. expectation failed: {expectation.describe()}"
                    )
                print(f"{step_number}. bot: {self._client.format_bot_reply(match)}")
                continue

            raise ScenarioError(f"{step_number}. unknown step: {step}")

        print("scenario passed")


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
    pass


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ScenarioError as error:
        print(error)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        pass
