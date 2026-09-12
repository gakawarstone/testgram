from __future__ import annotations

import argparse

from testgram.server import serve


async def serve_command(args: argparse.Namespace) -> None:
    await serve(host=args.host, port=args.port, log_file=args.log_file)
