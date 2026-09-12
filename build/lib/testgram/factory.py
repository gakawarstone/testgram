from __future__ import annotations

from .client import TestgramClient


def create_client(
    base_url: str,
    chat_id: int,
    username: str = "test_user",
    first_name: str = "Test",
) -> TestgramClient:
    return TestgramClient(
        base_url=base_url,
        chat_id=chat_id,
        username=username,
        first_name=first_name,
    )
