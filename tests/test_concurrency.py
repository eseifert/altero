"""Concurrent writes to one library.

These run against PostgreSQL, because SQLite serializes writers and so cannot
show the race they are about. They are skipped when no server is reachable; set
``ALTERO_TEST_POSTGRES_URL`` to point at one, for example::

    docker run -d -e POSTGRES_PASSWORD=altero -e POSTGRES_USER=altero \\
        -e POSTGRES_DB=altero -p 55432:5432 postgres:18-alpine
    ALTERO_TEST_POSTGRES_URL=postgresql+asyncpg://altero:altero@localhost:55432/altero
"""

import asyncio
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from altero.app import create_app
from altero.db import Database
from altero.models import ApiKey, Item, Library, LibraryType, Tag, User
from altero.settings import Settings

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

POSTGRES_URL = os.environ.get("ALTERO_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ALTERO_TEST_POSTGRES_URL is not set")


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    """Return a database with a schema created fresh for this test."""
    assert POSTGRES_URL
    database = Database(Settings(database_url=POSTGRES_URL))

    from altero.db import Base

    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with database.session_factory() as session:
        session.add(User(id=1, username="octocat"))
        await session.flush()
        session.add(Library(type=LibraryType.USER, owner_id=1, version=0))
        session.add(ApiKey(key=KEY, user_id=1, library_read=True, library_write=True))
        await session.commit()

    yield database
    await database.dispose()


@pytest.fixture
async def client(database: Database) -> AsyncIterator[httpx.AsyncClient]:
    """Return a client whose app shares the prepared database."""
    assert POSTGRES_URL
    app = create_app(Settings(database_url=POSTGRES_URL))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await app.state.database.dispose()


async def test_concurrent_creates_each_get_their_own_version(
    client: httpx.AsyncClient, database: Database
) -> None:
    """No two requests may share a library version.

    Reading the version, adding one and storing it back would hand the same
    number to both of ten simultaneous requests, and a client syncing on
    ``since`` would never see the objects that shared a version with an earlier
    write.
    """
    responses = await asyncio.gather(
        *(
            client.post(
                "/users/1/items",
                headers=AUTH,
                json=[{"itemType": "book", "title": f"Book {index}"}],
            )
            for index in range(10)
        )
    )

    assert [r.status_code for r in responses] == [200] * 10

    versions = [int(r.headers["Last-Modified-Version"]) for r in responses]
    assert len(set(versions)) == 10, f"versions collided: {sorted(versions)}"
    assert sorted(versions) == list(range(1, 11))


async def test_no_write_is_lost(client: httpx.AsyncClient, database: Database) -> None:
    """Every concurrent create must survive."""
    await asyncio.gather(
        *(
            client.post(
                "/users/1/items",
                headers=AUTH,
                json=[{"itemType": "book", "title": f"Book {index}"}],
            )
            for index in range(10)
        )
    )

    async with database.session_factory() as session:
        stored = list(await session.scalars(select(Item)))

    assert len(stored) == 10
    assert len({item.version for item in stored}) == 10


async def test_the_library_version_matches_the_newest_object(
    client: httpx.AsyncClient, database: Database
) -> None:
    await asyncio.gather(
        *(
            client.post("/users/1/items", headers=AUTH, json=[{"itemType": "book"}])
            for _ in range(8)
        )
    )

    async with database.session_factory() as session:
        library = await session.scalar(select(Library))
        newest = await session.scalar(select(Item).order_by(Item.version.desc()))

    assert library is not None
    assert newest is not None
    assert library.version == newest.version == 8


async def test_the_same_write_token_is_honoured_once(
    client: httpx.AsyncClient, database: Database
) -> None:
    """Two copies of one request must not both be applied.

    This is the case a check-then-insert cannot cover: both copies look, both
    find the token absent, and both proceed.
    """
    token = "a" * 32
    responses = await asyncio.gather(
        *(
            client.post(
                "/users/1/items",
                headers=AUTH | {"Zotero-Write-Token": token},
                json=[{"itemType": "book", "title": "Only once"}],
            )
            for _ in range(5)
        )
    )

    accepted = [r for r in responses if r.status_code == 200]
    rejected = [r for r in responses if r.status_code == 412]

    assert len(accepted) == 1, [r.status_code for r in responses]
    assert len(rejected) == 4

    async with database.session_factory() as session:
        assert len(list(await session.scalars(select(Item)))) == 1


async def test_the_same_new_tag_is_created_once(
    client: httpx.AsyncClient, database: Database
) -> None:
    """Concurrent writes naming one new tag must not duplicate it."""
    responses = await asyncio.gather(
        *(
            client.post(
                "/users/1/items",
                headers=AUTH,
                json=[
                    {
                        "itemType": "book",
                        "title": f"Book {index}",
                        "tags": [{"tag": "shared"}],
                    }
                ],
            )
            for index in range(8)
        )
    )

    assert [r.status_code for r in responses] == [200] * 8

    async with database.session_factory() as session:
        tags = list(await session.scalars(select(Tag).where(Tag.name == "shared")))

    assert len(tags) == 1

    body = (await client.get("/users/1/tags", headers=AUTH)).json()
    assert [t["tag"] for t in body] == ["shared"]
    assert body[0]["meta"]["numItems"] == 8


async def test_two_sweeps_at_once_send_one_digest(database: Database) -> None:
    """The claim is what stops a member being mailed twice about one burst.

    Two sweeps overlap whenever an instance runs more than one worker, or when
    one sweep runs long enough that the next tick starts beside it. Both would
    otherwise match ``flushed IS NULL``, render the same rows and send the same
    digest to the same people.
    """
    from datetime import UTC, datetime, timedelta

    from altero.models import ActivityKind, Group, GroupActivity, GroupMember, Notification
    from altero.services import groupdigest
    from altero.services.mail import Message

    async with database.session_factory() as session:
        session.add(User(id=2, username="bob", email="bob@example.org"))
        await session.flush()
        session.add(Library(type=LibraryType.USER, owner_id=2, version=0))
        library = Library(type=LibraryType.GROUP, owner_id=100, name="Kollaps", version=1)
        session.add(library)
        await session.flush()
        session.add(Group(library_id=library.id, owner_id=1, name="Kollaps"))
        session.add(GroupMember(library_id=library.id, user_id=1, role="admin"))
        session.add(
            GroupMember(library_id=library.id, user_id=2, role="member", notify_items_changed=True)
        )
        # Already settled, so both sweeps consider it due.
        session.add(
            GroupActivity(
                library_id=library.id,
                actor_id=1,
                kind=ActivityKind.ITEMS_CHANGED,
                count=4,
                created=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
            )
        )
        await session.commit()

    sent: list[Message] = []

    async def notify(message: Message) -> bool:
        sent.append(message)
        return True

    async def sweep() -> int:
        async with database.session_factory() as session:
            return await groupdigest.sweep(session, notify, quiet_period=timedelta(minutes=15))

    results = await asyncio.gather(sweep(), sweep(), sweep())

    assert sum(results) == 1
    assert len(sent) == 1
    async with database.session_factory() as session:
        notices = list(await session.scalars(select(Notification)))
    assert len(notices) == 1
