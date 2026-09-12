from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import ClientConnectorError, ClientSession

from testgram.chat import open_chat
from testgram.commands.run import BotProcess
from testgram.commands.run import wait_for_server
from testgram.config import load_project_config
from testgram.factory import create_client
from testgram.server import RunningServer, start_server


async def chat_command(args: argparse.Namespace) -> None:
    config = load_project_config(args.config, start=Path.cwd())
    server = await ensure_chat_server(args.url)
    server_url = server.url if server is not None else args.url
    bot = BotProcess(config=config, server_url=server_url, enabled=not args.no_bot)
    client = create_client(
        base_url=server_url,
        chat_id=args.chat_id,
        username=args.username,
        first_name=args.first_name,
    )
    try:
        polling_count = None
        if not args.no_bot and config.bot.command is not None:
            async with ClientSession() as session:
                polling_count = await client.get_polling_count(session)
        bot_started = await bot.start()
        await open_chat(
            client=client,
            timeout=args.timeout,
            reset=args.reset,
            polling_after=polling_count if bot_started else None,
        )
    finally:
        await bot.stop()
        if server is not None:
            await server.close()


async def ensure_chat_server(url: str) -> RunningServer | None:
    try:
        await wait_for_server(url)
        return None
    except ClientConnectorError as error:
        connector_error = error

    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise connector_error

    port = parsed.port or 80
    server = await start_server(
        host=parsed.hostname,
        port=port,
        quiet=True,
    )
    print(f"testgram listening on {server.url}")
    return server
