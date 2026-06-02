from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from .app import create_app


async def serve(host: str, port: int, log_file: Path | None = None) -> None:
    app = create_app(log_file=log_file)
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    print(f"testgram listening on http://{host}:{port}")
    print("control: POST /testgram/messages, GET /testgram/events, POST /testgram/reset")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()
