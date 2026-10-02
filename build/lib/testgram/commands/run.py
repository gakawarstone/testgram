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
from testgram.server import start_server

SCENARIO_SUFFIXES = {".json", ".yaml", ".yml"}


async def run_command(args: argparse.Namespace) -> None:
    if args.parallel < 1:
        raise ScenarioError("--parallel must be at least 1")

    config = load_project_config(args.config, start=args.scenario)
    scenario_paths = discover_scenarios(args.scenario)
    if args.parallel > 1 and len(scenario_paths) > 1 and args.port != 0:
        raise ScenarioError(
            "--port must be 0 when running multiple scenarios in parallel"
        )
    scenarios = [
        Scenario.from_file(scenario_path, default_timeout=args.timeout)
        for scenario_path in scenario_paths
    ]

    semaphore = asyncio.Semaphore(args.parallel)

    async def run_one(index: int, scenario: Scenario) -> None:
        async with semaphore:
            await run_scenario_isolated(
                args=args,
                config=config,
                scenario=scenario,
                chat_id=args.chat_id + index,
            )

    if args.parallel == 1:
        for index, scenario in enumerate(scenarios):
            await run_one(index, scenario)
    else:
        await asyncio.gather(
            *(run_one(index, scenario) for index, scenario in enumerate(scenarios))
        )


async def run_scenario_isolated(
    *,
    args: argparse.Namespace,
    config: ProjectConfig,
    scenario: Scenario,
    chat_id: int,
) -> None:
    server = await start_server(
        host=args.host,
        port=args.port,
        log_file=args.log_file,
        quiet=True,
    )
    bot = BotProcess(config=config, server_url=server.url, enabled=not args.no_bot)

    try:
        await wait_for_server(server.url)
        await bot.start()
        client = create_client(
            base_url=server.url,
            chat_id=chat_id,
            username=args.username,
            first_name=args.first_name,
        )
        await run_scenario(client=client, scenario=scenario, reset=not args.no_reset)
    except ScenarioError as error:
        diagnostics = await bot.diagnostics()
        if diagnostics and diagnostics not in error.message:
            raise ScenarioError(
                f"{error.message}\n\n{diagnostics}",
                path=error.path,
                line=error.line,
            ) from error
        raise
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
    _TAIL_BYTES = 32 * 1024

    def __init__(
        self,
        config: ProjectConfig,
        server_url: str,
        enabled: bool,
    ) -> None:
        self._config = config
        self._server_url = server_url
        self._enabled = enabled
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_tail = bytearray()
        self._stderr_tail = bytearray()
        self._reader_tasks: list[asyncio.Task[None]] = []

    async def start(self) -> bool:
        if not self._enabled or self._config.bot.command is None:
            return False

        cwd = None
        if self._config.path is not None:
            cwd = self._config.path.parent

        env = os.environ.copy()
        env.update(self._config.bot.env)
        env["API_SERVER_URL"] = self._server_url

        self._process = await asyncio.create_subprocess_shell(
            self._config.bot.command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if self._process.stdout is not None:
            self._reader_tasks.append(
                asyncio.create_task(
                    self._capture_stream(self._process.stdout, self._stdout_tail)
                )
            )
        if self._process.stderr is not None:
            self._reader_tasks.append(
                asyncio.create_task(
                    self._capture_stream(self._process.stderr, self._stderr_tail)
                )
            )
        await asyncio.sleep(0.2)
        if self._process.returncode is not None:
            await self._finish_readers()
            diagnostics = await self.diagnostics()
            suffix = f"\n\n{diagnostics}" if diagnostics else ""
            raise ScenarioError(
                f"bot command exited with code {self._process.returncode}: "
                f"{self._config.bot.command}{suffix}"
            )
        return True

    async def diagnostics(self) -> str:
        await asyncio.sleep(0)
        sections = []
        if self._process is not None and self._process.returncode is not None:
            sections.append(f"bot process exited with code {self._process.returncode}")
        if self._stdout_tail:
            sections.append(
                "bot stdout (tail):\n" + self._stdout_tail.decode(errors="replace").rstrip()
            )
        if self._stderr_tail:
            sections.append(
                "bot stderr (tail):\n" + self._stderr_tail.decode(errors="replace").rstrip()
            )
        return "\n\n".join(sections)

    async def _capture_stream(
        self,
        stream: asyncio.StreamReader,
        destination: bytearray,
    ) -> None:
        while chunk := await stream.read(4096):
            destination.extend(chunk)
            if len(destination) > self._TAIL_BYTES:
                del destination[: len(destination) - self._TAIL_BYTES]

    async def _finish_readers(self) -> None:
        if self._reader_tasks:
            await asyncio.gather(*self._reader_tasks, return_exceptions=True)

    async def stop(self) -> None:
        if self._process is None:
            return
        if self._process.returncode is not None:
            await self._finish_readers()
            return

        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()
        finally:
            await self._finish_readers()

async def wait_for_server(url: str) -> None:
    async with ClientSession() as session:
        async with session.get(f"{url}/testgram/health") as response:
            response.raise_for_status()
