from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from aiohttp import ClientConnectorError, ClientResponseError

from .commands.chat import chat_command
from .commands.run import run_command
from .commands.serve import serve_command
from .config import ConfigError
from .scenario import ScenarioError


DEFAULT_URL = "http://127.0.0.1:8081"


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    try:
        asyncio.run(args.command(args))
    except KeyboardInterrupt:
        pass
    except ClientConnectorError:
        print(
            "error: could not connect to the testgram server",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except ClientResponseError as error:
        print(
            f"error: testgram server returned HTTP {error.status} for {error.request_info.real_url}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except TimeoutError:
        print("error: request to the testgram server timed out", file=sys.stderr)
        raise SystemExit(1) from None
    except ScenarioError as error:
        print(error)
        raise SystemExit(1) from error
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="testgram",
        description="Fake Telegram Bot API server for manual bot testing.",
    )
    subcommands = parser.add_subparsers(dest="command_name", required=True)

    serve = subcommands.add_parser("serve", help="run the fake Bot API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8081, type=int)
    serve.add_argument("--log-file", type=Path)
    serve.set_defaults(command=serve_command)

    chat = subcommands.add_parser("chat", help="open an interactive chat")
    add_client_args(chat)
    chat.add_argument("--reset", action="store_true")
    chat.set_defaults(command=chat_command)

    run = subcommands.add_parser("run", help="run a scenario file or directory")
    run.add_argument("scenario", type=Path)
    run.add_argument("--config", type=Path)
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", default=0, type=int)
    run.add_argument("--log-file", type=Path)
    run.add_argument("--no-bot", action="store_true")
    add_client_args(run, include_url=False)
    run.add_argument("--no-reset", action="store_true")
    run.set_defaults(command=run_command)

    return parser.parse_args(argv)


def add_client_args(parser: argparse.ArgumentParser, include_url: bool = True) -> None:
    if include_url:
        parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--chat-id", default=1, type=int)
    parser.add_argument("--username", default="test_user")
    parser.add_argument("--first-name", default="Test")
    parser.add_argument("--timeout", default=15.0, type=float)
