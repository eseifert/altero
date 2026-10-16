"""Concurrent writes to one library on SQLite.

SQLite serializes writers, but only from a transaction's first write. The
precondition a write checks is read before that, so two requests holding the
same library version could both pass it -- the second applied over changes its
client had never seen. `tests/test_concurrency.py` holds PostgreSQL to the same
rule with its row lock.
"""

import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}


async def test_two_writes_from_one_version_cannot_both_land(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()

    responses = await asyncio.gather(
        *(
            client.post(
                "/users/1/items",
                headers=AUTH | {"If-Unmodified-Since-Version": "10"},
                json=[
                    {"itemType": "book", "title": f"From client {client_index} #{n}"}
                    for n in range(20)
                ],
            )
            for client_index in range(2)
        )
    )

    assert sorted(r.status_code for r in responses) == [200, 412]
