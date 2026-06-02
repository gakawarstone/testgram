from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aiohttp import web

from testgram.app import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fake Telegram Bot API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8081, type=int)
    parser.add_argument("--log-file", type=Path)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    app = create_app(log_file=args.log_file)
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    print(f"testgram listening on http://{args.host}:{args.port}")
    print("control: POST /testgram/messages, GET /testgram/events, POST /testgram/reset")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
