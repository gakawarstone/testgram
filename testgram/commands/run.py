from __future__ import annotations

import argparse

from testgram.factory import create_client
from testgram.scenario import Scenario, run_scenario


async def run_command(args: argparse.Namespace) -> None:
    client = create_client(
        base_url=args.url,
        chat_id=args.chat_id,
        username=args.username,
        first_name=args.first_name,
    )
    scenario = Scenario.from_file(args.scenario, default_timeout=args.timeout)
    await run_scenario(client=client, scenario=scenario, reset=not args.no_reset)
