from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
from pathlib import Path

from aiohttp import ClientSession

from testgram.config import ProjectConfig, load_project_config
from testgram.factory import create_client
from testgram.scenario import Scenario, ScenarioError, run_scenario
from testgram.server import RunningServer, start_server

SCENARIO_SUFFIXES = {".json", ".yaml", ".yml"}


async def run_command(args: argparse.Namespace) -> None:
    config = load_project_config(args.config, start=args.scenario)
    scenario_paths = discover_scenarios(args.scenario)
    server = await start_server(
        host=args.host,
        port=args.port,
        log_file=args.log_file,
        quiet=True,
    )
    bot = BotProcess(config=config, server=server, enabled=not args.no_bot)

    try:
        await wait_for_server(server.url)
        await bot.start()

        client = create_client(
            base_url=server.url,
            chat_id=args.chat_id,
            username=args.username,
            first_name=args.first_name,
        )
        for scenario_path in scenario_paths:
            scenario = Scenario.from_file(scenario_path, default_timeout=args.timeout)
            await run_scenario(client=client, scenario=scenario, reset=not args.no_reset)
    finally:
        await bot.stop()
        await server.close()


def discover_scenarios(path: Path) -> list[Path]:
    if path.is_dir():
        scenarios = sorted(
            candidate
            for candidate in path.iterdir()
            if candidate.is_file() and candidate.suffix.lower() in SCENARIO_SUFFIXES
        )
        if not scenarios:
            raise ScenarioError(f"{path}: no scenario files found")
        return scenarios

    if path.suffix.lower() not in SCENARIO_SUFFIXES:
        raise ScenarioError(f"{path}: unsupported scenario file extension")
    return [path]


class BotProcess:
    def __init__(
        self,
        config: ProjectConfig,
        server: RunningServer,
        enabled: bool,
    ) -> None:
        self._config = config
        self._server = server
        self._enabled = enabled
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if not self._enabled or self._config.bot.command is None:
            return

        env = os.environ.copy()
        env.update(self._config.bot.env)
        env["API_SERVER_URL"] = self._server.url

        cwd = None
        if self._config.path is not None:
            cwd = self._config.path.parent

        self._process = await asyncio.create_subprocess_shell(
            self._config.bot.command,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.sleep(0.2)
        if self._process.returncode is not None:
            raise ScenarioError(
                f"bot command exited with code {self._process.returncode}: "
                f"{self._config.bot.command}"
            )

    async def stop(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()


async def wait_for_server(url: str) -> None:
    async with ClientSession() as session:
        async with session.get(f"{url}/testgram/health") as response:
            response.raise_for_status()
