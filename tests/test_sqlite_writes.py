"""Concurrent writes to one library on SQLite.

SQLite serializes writers, but only from a transaction's first write. The
precondition a write checks is read before that, so two requests holding the
same library version could both pass it -- the second applied over changes its
client had never seen. `tests/test_concurrency.py` holds PostgreSQL to the same
rule with its row lock.
"""

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero import db
from altero.models import LibraryType
from altero.services.auth import get_library
from altero.settings import Settings
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


class TestABusyDatabase:
    """A write that cannot get SQLite's lock in time is told to come back.

    The desktop client retries a 503 that carries an integer ``Retry-After``
    (``Zotero.Sync.APIClient._checkRetry``) and gives up on a 500, so a write
    that merely lost the race for the lock must not look like a server fault.
    Nothing was written: the lock is taken before anything else.
    """

    @pytest.fixture
    async def client(self, app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
        """A client that sees what a real one would: a status, not a traceback."""
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client

    @pytest.fixture
    def held(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[sqlite3.Connection]:
        monkeypatch.setattr(db, "BUSY_TIMEOUT_MS", 50)
        path = settings.database_url.removeprefix("sqlite+aiosqlite:///")
        holder = sqlite3.connect(path, isolation_level=None)
        yield holder
        holder.close()

    async def test_the_write_answers_503_with_retry_after(
        self, client: httpx.AsyncClient, session: AsyncSession, held: sqlite3.Connection
    ) -> None:
        await make_user(session, user_id=1)
        await make_api_key(session, key=KEY, user_id=1)
        held.execute("BEGIN IMMEDIATE")

        response = await client.post("/users/1/items", headers=AUTH, json=[{"itemType": "book"}])

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        held.execute("ROLLBACK")
        retried = await client.post("/users/1/items", headers=AUTH, json=[{"itemType": "book"}])
        assert retried.status_code == 200

    async def test_the_browser_hears_it_in_json(
        self, client: httpx.AsyncClient, held: sqlite3.Connection
    ) -> None:
        from tests.test_web_routes import register

        held.execute("BEGIN IMMEDIATE")
        response = await register(client)

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert "message" in response.json()
        held.execute("ROLLBACK")


async def test_any_other_database_failure_is_still_a_fault() -> None:
    """Only the lock is retryable; a missing table is a fault and stays one."""
    from sqlalchemy.exc import OperationalError
    from starlette.requests import Request

    from altero.api.errors import handle_operational_error

    with pytest.raises(sqlite3.OperationalError) as caught:
        sqlite3.connect(":memory:").execute("SELECT * FROM nowhere")
    failure = OperationalError("SELECT * FROM nowhere", {}, caught.value)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    with pytest.raises(OperationalError):
        await handle_operational_error(request, failure)
