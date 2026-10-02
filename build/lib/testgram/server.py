from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from .app import create_app


@dataclass(slots=True)
class RunningServer:
    host: str
    port: int
    runner: web.AppRunner

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def close(self) -> None:
        await self.runner.cleanup()


async def start_server(
    host: str,
    port: int,
    log_file: Path | None = None,
    quiet: bool = False,
) -> RunningServer:
    app = create_app(log_file=log_file, quiet=quiet)
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()
    sockets = site._server.sockets if site._server is not None else None
    if sockets is None:
        raise RuntimeError("testgram server started without a bound socket")
    bound_port = int(sockets[0].getsockname()[1])

    return RunningServer(host=host, port=bound_port, runner=runner)


async def serve(host: str, port: int, log_file: Path | None = None) -> None:
    server = await start_server(host=host, port=port, log_file=log_file)

    print(f"testgram listening on {server.url}")
    print("control: POST /testgram/messages, GET /testgram/events, POST /testgram/reset")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await server.close()
