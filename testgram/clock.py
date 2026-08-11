from __future__ import annotations

import os
import math

from aiohttp import ClientSession, ClientTimeout


def time_url() -> str:
    try:
        return os.environ["TESTGRAM_TIME_URL"]
    except KeyError as error:
        raise RuntimeError("TESTGRAM_TIME_URL is not set") from error


async def now() -> float:
    async with ClientSession() as session:
        async with session.get(time_url()) as response:
            response.raise_for_status()
            return float((await response.json())["result"]["unix"])


async def sleep(seconds: float, *, request_timeout: float = 86_400) -> None:
    """Sleep until the shared Testgram clock advances by ``seconds``."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("seconds must be non-negative")
    target = await now() + seconds
    async with ClientSession(
        timeout=ClientTimeout(total=request_timeout + 1)
    ) as session:
        async with session.get(
            time_url(), params={"until": target, "timeout": request_timeout}
        ) as response:
            response.raise_for_status()
            current = float((await response.json())["result"]["unix"])
    if current < target:
        raise TimeoutError(f"virtual clock did not reach {target:g}")
