from __future__ import annotations

import asyncio

from aiohttp import ClientSession

from .client import TestgramClient


async def open_chat(client: TestgramClient, timeout: float, reset: bool) -> None:
    async with ClientSession() as session:
        if reset:
            await client.reset(session)

        seen_events = len(await client.get_events(session))
        print("testgram chat. Ctrl+C or /exit to quit.")

        while True:
            try:
                text = await asyncio.to_thread(input, "me: ")
            except EOFError:
                break

            if text.strip() in {"/exit", "/quit"}:
                break
            if text == "":
                continue

            await client.send_message(session, text)
            bot_events, seen_events = await client.wait_for_bot_events(
                session=session,
                seen_events=seen_events,
                timeout=timeout,
            )
            if bot_events:
                seen_events = bot_events[-1][0] + 1
            if not bot_events:
                print("bot: <no response>")
            for _, event in bot_events:
                print(f"bot: {client.format_bot_reply(event)}")
