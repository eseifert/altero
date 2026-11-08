"""The browser's feed of library versions, ``/web/libraries/<id>/events``.

Against uvicorn on a port, as ``test_sync_cycle`` is: neither test client
streams a response that does not end, and this one ends only when the reader
hangs up or the server decides the reader may no longer listen.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from threading import Event

import anyio
import httpx2
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import QueuePool, event, text
from sqlalchemy.ext.asyncio import AsyncSession

from altero.api.routes import webevents
from altero.services import websessions
from altero.settings import Settings
from tests.test_web_routes import PASSWORD, csrf_headers

STARTUP_TIMEOUT = 15.0

#: How long a test waits for an event before deciding it is not coming.
TIMEOUT = 10.0


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'events.sqlite'}",
        storage_path=tmp_path / "storage",
        # A second account, to show what one reader is not told.
        open_registration=True,
    )


@pytest.fixture
async def server(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """Run the real server on an ephemeral port and yield its base URL."""
    # A heartbeat a test can wait for: it is when a reader's right to listen
    # is asked again.
    monkeypatch.setattr(webevents, "HEARTBEAT_SECONDS", 0.2)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="error", access_log=False, lifespan="on"
    )
    running = uvicorn.Server(config)
    task = asyncio.create_task(running.serve())
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while not running.started:
        if task.done():  # pragma: no cover - surfaces a startup failure
            task.result()
        if time.monotonic() > deadline:  # pragma: no cover
            raise TimeoutError("server did not start")
        await asyncio.sleep(0.01)

    port = running.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        running.should_exit = True
        await task


async def test_disconnect_during_a_feed_read_returns_its_connection(
    app: FastAPI, server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Close a real socket while SQLite is checking the feed's session."""
    client = await signed_in(server)
    library = await library_id(client)
    entered = Event()
    released = Event()
    invalidated = asyncio.Event()
    returned = asyncio.Event()
    engine = app.state.database.engine.sync_engine

    def held_read() -> int:
        entered.set()
        assert released.wait(10), "The test did not release the SQLite worker"
        return 1

    # Install on the existing pooled connections too, before opening the feed.
    async with app.state.database.engine.connect() as connection:
        await connection.run_sync(
            lambda sync: sync.connection.create_function("held_read", 0, held_read)
        )

    @event.listens_for(engine, "invalidate")
    def on_invalidate(_connection, _record, _exception) -> None:
        invalidated.set()

    @event.listens_for(engine, "checkin")
    def on_checkin(_connection, _record) -> None:
        if invalidated.is_set():
            returned.set()

    lookup = websessions.lookup
    calls = 0

    async def held_lookup(session: AsyncSession, token: str | None):
        nonlocal calls
        calls += 1
        # The route authenticates first; the streaming body checks again.
        if calls == 2:
            await session.execute(text("SELECT held_read()"))
        return await lookup(session, token)

    monkeypatch.setattr(websessions, "lookup", held_lookup)
    try:
        async with client.stream("GET", f"/web/libraries/{library}/events") as response:
            assert response.status_code == 200
            assert await asyncio.to_thread(entered.wait, 10)
            await response.aclose()
        await asyncio.wait_for(invalidated.wait(), TIMEOUT)
        released.set()
        with anyio.move_on_after(TIMEOUT):
            await returned.wait()
        assert returned.is_set(), "Disconnect cleanup did not return the pool slot"

        pool = engine.pool
        assert isinstance(pool, QueuePool)
        assert pool.checkedout() == 0
        assert await add_item(client, library) > 0
    finally:
        released.set()
        await client.aclose()


async def signed_in(server: str, username: str = "ada") -> httpx2.AsyncClient:
    client = httpx2.AsyncClient(base_url=server, timeout=30)
    registered = await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "email": f"{username}@example.org",
            "displayName": username,
        },
    )
    assert registered.status_code == 201, registered.text
    return client


async def library_id(client: httpx2.AsyncClient) -> int:
    return (await client.get("/web/libraries")).json()[0]["id"]


async def add_item(client: httpx2.AsyncClient, library: int) -> int:
    """Write through the browser's own route, and return the new library version."""
    created = await client.post(
        f"/web/libraries/{library}/items",
        json={"itemType": "book"},
        headers=csrf_headers(client),  # type: ignore[arg-type]
    )
    assert created.status_code == 201, created.text
    return int(created.headers["Last-Modified-Version"])


class Feed:
    """The events one open stream has delivered, read as they arrive."""

    def __init__(self, response: httpx2.Response) -> None:
        self.response = response
        self.lines = response.aiter_lines()

    async def next(self) -> dict[str, object] | None:
        """The next event, or ``None`` once the server has ended the stream."""
        event: dict[str, object] = {}
        try:
            async with asyncio.timeout(TIMEOUT):
                async for line in self.lines:
                    if line.startswith(":"):
                        continue
                    if not line:
                        if "event" in event:
                            return event
                        continue
                    name, _, value = line.partition(": ")
                    event[name] = json.loads(value) if name == "data" else value
        except TimeoutError:
            pytest.fail(f"No event arrived within {TIMEOUT} seconds")
        return None


class TestTheFeed:
    async def test_it_starts_with_the_version_the_library_has(self, server: str) -> None:
        client = await signed_in(server)
        library = await library_id(client)
        version = await add_item(client, library)

        async with client.stream("GET", f"/web/libraries/{library}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-store"
            first = await Feed(response).next()

        assert first == {
            "retry": str(webevents.RETRY_MILLISECONDS),
            "event": "version",
            "data": {"version": version},
        }
        await client.aclose()

    async def test_a_write_to_the_library_is_announced_with_its_version(self, server: str) -> None:
        client = await signed_in(server)
        library = await library_id(client)

        async with client.stream("GET", f"/web/libraries/{library}/events") as response:
            feed = Feed(response)
            await feed.next()
            version = await add_item(client, library)
            announced = await feed.next()

        assert announced == {"event": "version", "data": {"version": version}}
        await client.aclose()

    async def test_another_library_s_writes_are_not_announced(self, server: str) -> None:
        ada = await signed_in(server)
        library = await library_id(ada)
        grace = await signed_in(server, "grace")
        theirs = await library_id(grace)
        # Ahead of Grace's, so that her version and Ada's next cannot coincide.
        await add_item(ada, library)

        async with ada.stream("GET", f"/web/libraries/{library}/events") as response:
            feed = Feed(response)
            await feed.next()
            await add_item(grace, theirs)
            version = await add_item(ada, library)
            announced = await feed.next()

        assert announced == {"event": "version", "data": {"version": version}}
        await ada.aclose()
        await grace.aclose()

    async def test_it_needs_a_session(self, server: str) -> None:
        async with httpx2.AsyncClient(base_url=server) as stranger:
            response = await stranger.get("/web/libraries/1/events")

        assert response.status_code == 401

    async def test_a_library_the_reader_cannot_read_is_refused(self, server: str) -> None:
        ada = await signed_in(server)
        grace = await signed_in(server, "grace")

        response = await grace.get(f"/web/libraries/{await library_id(ada)}/events")

        assert response.status_code == 403
        await ada.aclose()
        await grace.aclose()

    async def test_signing_out_ends_the_feed(self, server: str) -> None:
        """A version is not much, but a session that has ended reads nothing."""
        client = await signed_in(server)
        library = await library_id(client)

        async with client.stream("GET", f"/web/libraries/{library}/events") as response:
            feed = Feed(response)
            await feed.next()
            async with httpx2.AsyncClient(base_url=server, cookies=client.cookies) as other_tab:
                signed_out = await other_tab.post(
                    "/web/auth/logout",
                    headers=csrf_headers(other_tab),  # type: ignore[arg-type]
                )
                assert signed_out.status_code == 204, signed_out.text
            ended = await feed.next()

        assert ended is None
        await client.aclose()


class TestLosingAccess:
    async def test_a_group_made_private_ends_a_stranger_s_feed(self, server: str) -> None:
        """Read a public group's feed as somebody outside it, then close the group."""
        ada = await signed_in(server)
        made = await ada.post(
            "/web/groups",
            json={"name": "Whale Watchers", "type": "PublicOpen", "libraryReading": "all"},
            headers=csrf_headers(ada),  # type: ignore[arg-type]
        )
        assert made.status_code == 201, made.text
        group = made.json()["id"]
        grace = await signed_in(server, "grace")

        async with grace.stream("GET", f"/web/libraries/{group}/events") as response:
            assert response.status_code == 200
            feed = Feed(response)
            await feed.next()
            closed = await ada.patch(
                f"/web/groups/{group}",
                json={"type": "Private"},
                headers=csrf_headers(ada),  # type: ignore[arg-type]
            )
            assert closed.status_code == 200, closed.text
            # The version the change produced may come first; the feed ends after.
            while await feed.next() is not None:
                pass

        await ada.aclose()
        await grace.aclose()
