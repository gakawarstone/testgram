from __future__ import annotations

import argparse
import asyncio

from aiohttp import ClientSession

from testgram.client import TestgramClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive testgram chat")
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--chat-id", default=1, type=int)
    parser.add_argument("--username", default="test_user")
    parser.add_argument("--first-name", default="Test")
    parser.add_argument("--timeout", default=15.0, type=float)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    client = TestgramClient(
        base_url=args.url.rstrip("/"),
        chat_id=args.chat_id,
        username=args.username,
        first_name=args.first_name,
    )

    async with ClientSession() as session:
        if args.reset:
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
                timeout=args.timeout,
            )
            if not bot_events:
                print("bot: <no response>")
            for event in bot_events:
                print(f"bot: {client.format_bot_reply(event)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
