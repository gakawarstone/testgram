from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from aiohttp import ClientSession

from testgram.config import ProjectConfig, load_project_config
from testgram.factory import create_client
from testgram.client import TestgramClient
from testgram.scenario import Scenario, ScenarioError, run_scenario
from testgram.server import RunningServer, start_server

SCENARIO_SUFFIXES = {".json", ".yaml", ".yml"}


async def run_command(args: argparse.Namespace) -> None:
    if args.parallel < 1:
        raise ScenarioError("--parallel must be at least 1")

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
        scenarios = [
            Scenario.from_file(scenario_path, default_timeout=args.timeout)
            for scenario_path in scenario_paths
        ]
        if args.parallel == 1:
            for scenario in scenarios:
                await run_scenario(client=client, scenario=scenario, reset=not args.no_reset)
        else:
            await run_scenarios_parallel(
                client=client,
                scenarios=scenarios,
                parallel=args.parallel,
                reset=not args.no_reset,
            )
    finally:
        await bot.stop()
        await server.close()


async def run_scenarios_parallel(
    client: TestgramClient,
    scenarios: list[Scenario],
    parallel: int,
    reset: bool,
) -> None:
    if reset:
        async with ClientSession() as session:
            await client.reset(session)

    semaphore = asyncio.Semaphore(parallel)

    async def run_one(index: int, scenario: Scenario) -> None:
        async with semaphore:
            scenario_client = TestgramClient(
                base_url=client.base_url,
                chat_id=client.chat_id + index,
                username=client.username,
                first_name=client.first_name,
            )
            await run_scenario(client=scenario_client, scenario=scenario, reset=False)

    await asyncio.gather(
        *(run_one(index, scenario) for index, scenario in enumerate(scenarios))
    )


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
        self._reused_existing = False

    async def start(self) -> None:
        if not self._enabled or self._config.bot.command is None:
            return

        cwd = None
        if self._config.path is not None:
            cwd = self._config.path.parent

        if is_command_running(self._config.bot.command, cwd=cwd):
            self._reused_existing = True
            print(
                f"bot command already running; not starting another: "
                f"{self._config.bot.command}",
                file=sys.stderr,
            )
            return

        env = os.environ.copy()
        env.update(self._config.bot.env)
        env["API_SERVER_URL"] = self._server.url

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
        if (
            self._reused_existing
            or self._process is None
            or self._process.returncode is not None
        ):
            return

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()


def is_command_running(command: str, cwd: Path | None) -> bool:
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return False

    expected_command = normalize_command(command)
    expected_cwd = cwd.resolve() if cwd is not None else None
    current_pid = os.getpid()

    for pid_dir in proc_dir.iterdir():
        if not pid_dir.name.isdecimal() or int(pid_dir.name) == current_pid:
            continue

        try:
            if expected_cwd is not None and pid_dir.joinpath("cwd").resolve() != expected_cwd:
                continue

            raw_cmdline = pid_dir.joinpath("cmdline").read_bytes()
        except (FileNotFoundError, OSError, PermissionError):
            continue

        if not raw_cmdline:
            continue

        process_command = normalize_command(
            raw_cmdline.replace(b"\0", b" ").decode(errors="replace")
        )
        if expected_command in process_command:
            return True

    return False


def normalize_command(command: str) -> str:
    return " ".join(command.split())


async def wait_for_server(url: str) -> None:
    async with ClientSession() as session:
        async with session.get(f"{url}/testgram/health") as response:
            response.raise_for_status()
