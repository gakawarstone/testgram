from __future__ import annotations

import argparse

from testgram.chat import open_chat
from testgram.factory import create_client


async def chat_command(args: argparse.Namespace) -> None:
    client = create_client(
        base_url=args.url,
        chat_id=args.chat_id,
        username=args.username,
        first_name=args.first_name,
    )
    await open_chat(client=client, timeout=args.timeout, reset=args.reset)
