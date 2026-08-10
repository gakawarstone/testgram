from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .console import EventLogger
from .storage import MemoryStorage
from .telegram_api import TelegramApi


def create_app(log_file: Path | None = None, quiet: bool = False) -> web.Application:
    storage = MemoryStorage()
    logger = EventLogger(log_file=log_file, quiet=quiet)
    telegram_api = TelegramApi(storage=storage, logger=logger)

    app = web.Application(client_max_size=50 * 1024**2)
    app["storage"] = storage
    app["logger"] = logger

    app.router.add_post("/bot{token}/{method}", telegram_api.handle_method)
    app.router.add_get("/testgram/events", telegram_api.get_events)
    app.router.add_post("/testgram/messages", telegram_api.create_message)
    app.router.add_post("/testgram/callbacks", telegram_api.create_callback_query)
    app.router.add_post("/testgram/reset", telegram_api.reset)
    app.router.add_get("/testgram/health", telegram_api.health)
    app.router.add_get("/testgram/polling", telegram_api.polling_status)

    return app
