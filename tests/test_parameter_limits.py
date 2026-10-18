"""No statement binds a value per object of a library.

SQLite refuses a statement with more than 32,766 bound variables and asyncpg
one with more than 32,767, so an ``IN`` built from a Python list that grows with
a library stops working outright past that size. Filling a library to 33,000
objects per test would be slow, so these assert the shape instead: with the
chunk size turned down, no statement binds more than a handful of values
however many objects are involved.

``INSERT`` statements are left out. Each row is its own set of parameters, and
where SQLAlchemy folds several rows into one statement it keeps under
`insertmanyvalues_max_parameters` by itself.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategies import SelectInLoader

from altero import db
from altero.models import (
    ActivityKind,
    GroupActivity,
    GroupActivityObject,
    Item,
    Library,
    LibraryType,
    StorageDownload,
    WebSession,
)
from altero.query import ListQuery
from altero.services import duplicates, groupactivity, items, retention, transfer
from altero.services.auth import get_library
from altero.services.items import Scope
from altero.services.itemwrites import delete_items
from altero.services.objectwrites import rename_tag
from tests.factories import make_group, make_item, make_user, tag_item

#: How many objects each test makes: more than the chunk size below, and more
#: than any statement here would bind if it did not grow with them.
OBJECTS = 40

#: The chunk size under test, small so that 40 objects take several chunks.
CHUNK = 8

#: The most values a statement may bind: a chunk, and a few besides it.
MOST = CHUNK + 8


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "CHUNK", CHUNK)
    # SQLAlchemy's eager loads chunk their ids on their own, 500 to a statement.
    monkeypatch.setattr(SelectInLoader, "_chunksize", CHUNK)


@contextmanager
def widest_statement(app: FastAPI) -> Iterator[list[tuple[int, str]]]:
    """Collect how many values each non-INSERT statement binds."""
    seen: list[tuple[int, str]] = []
    engine = app.state.database.engine.sync_engine

    def record(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT"):
            return
        rows = parameters if executemany else [parameters]
        seen.append((max((len(row) for row in rows), default=0), statement))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def assert_bounded(seen: list[tuple[int, str]]) -> None:
    assert seen, "nothing was executed"
    widest, statement = max(seen)
    assert widest <= MOST, f"{widest} values bound by: {' '.join(statement.split())[:300]}"


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    return await get_library(session, LibraryType.USER, 1)


async def many_items(session: AsyncSession, library: Library, **options: Any) -> list[Item]:
    return [await make_item(session, library, **options) for _ in range(OBJECTS)]


class TestReads:
    async def test_finding_duplicates(
        self, app: FastAPI, session: AsyncSession, library: Library
    ) -> None:
        await many_items(session, library, fields={"title": "The same work"})

        with widest_statement(app) as seen:
            found = await duplicates.duplicate_item_ids(session, library)

        assert len(found) == OBJECTS
        assert_bounded(seen)

    @pytest.mark.parametrize("scope", [Scope.DUPLICATES, Scope.RECENTLY_READ])
    async def test_listing_a_computed_scope(
        self, app: FastAPI, session: AsyncSession, library: Library, scope: Scope
    ) -> None:
        for _ in range(OBJECTS):
            parent = await make_item(session, library, fields={"title": "The same work"})
            await make_item(
                session,
                library,
                item_type="attachment",
                parent=parent,
                fields={"lastRead": str(int(now().replace(tzinfo=UTC).timestamp()))},
            )

        with widest_statement(app) as seen:
            page = await items.list_items(session, library, ListQuery(limit=5), scope=scope)

        assert page.total == OBJECTS
        assert_bounded(seen)

    async def test_exporting_an_archive(
        self, app: FastAPI, session: AsyncSession, library: Library, tmp_path: Path
    ) -> None:
        for index, item in enumerate(await many_items(session, library)):
            await tag_item(session, library, item, f"tag {index}")

        with widest_statement(app) as seen:
            await transfer.export_library(
                session,
                library_type=LibraryType.USER,
                owner_id=1,
                storage_root=tmp_path / "storage",
                destination=tmp_path / "archive.zip",
            )

        assert_bounded(seen)


class TestWrites:
    async def test_naming_items(
        self, app: FastAPI, session: AsyncSession, library: Library
    ) -> None:
        group = await make_group(session, owner_id=1)
        keys = [item.key for item in await many_items(session, group)]

        with widest_statement(app) as seen:
            named = await groupactivity.name_items(session, group, keys)

        assert [key for key, _name in named] == keys
        assert_bounded(seen)

    async def test_renaming_a_tag_on_every_item(
        self, app: FastAPI, session: AsyncSession, library: Library
    ) -> None:
        for item in await many_items(session, library):
            await tag_item(session, library, item, "old")

        with widest_statement(app) as seen:
            changed = await rename_tag(session, library, "old", "new", 5)

        assert len(changed) == OBJECTS
        assert_bounded(seen)

    async def test_deleting_items(
        self, app: FastAPI, session: AsyncSession, library: Library
    ) -> None:
        keys = [item.key for item in await many_items(session, library, deleted=True)]

        with widest_statement(app) as seen:
            await delete_items(session, library, keys, 5)
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(Item)) == 0
        assert_bounded(seen)


class TestRetention:
    async def test_sweeping_the_trash(
        self, app: FastAPI, session: AsyncSession, library: Library
    ) -> None:
        for item in await many_items(session, library, deleted=True):
            item.server_date_modified = now() - timedelta(days=40)
        await session.commit()

        with widest_statement(app) as seen:
            report = await retention.sweep(session, {"trashRetentionDays": 30})

        assert report.items_deleted == OBJECTS
        assert_bounded(seen)

    async def test_sweeping_delivered_activity(
        self, app: FastAPI, session: AsyncSession, library: Library
    ) -> None:
        group = await make_group(session, owner_id=1)
        for _ in range(OBJECTS):
            session.add(
                GroupActivity(
                    library_id=group.id,
                    actor_id=1,
                    kind=ActivityKind.ITEMS_CHANGED,
                    count=1,
                    created=now() - timedelta(days=400),
                    flushed=now() - timedelta(days=400),
                    objects=[GroupActivityObject(object_key="AAAA2345", name="x")],
                )
            )
        await session.commit()

        with widest_statement(app) as seen:
            report = await retention.sweep(session, {"activityRetentionDays": 365})

        assert report.activity == OBJECTS
        assert await session.scalar(select(func.count()).select_from(GroupActivityObject)) == 0
        assert_bounded(seen)

    @pytest.mark.parametrize("dry_run", [False, True])
    async def test_sweeping_what_expired(
        self, app: FastAPI, session: AsyncSession, library: Library, dry_run: bool
    ) -> None:
        item = await make_item(session, library, item_type="attachment")
        for index in range(OBJECTS):
            session.add(
                WebSession(token_hash=f"dead{index}", user_id=1, expires=now() - timedelta(days=1))
            )
            session.add(
                StorageDownload(
                    key=f"spent{index}",
                    item_id=item.id,
                    library_id=library.id,
                    md5="d41d8cd98f00b204e9800998ecf8427e",
                    expires=now() - timedelta(minutes=1),
                )
            )
        await session.commit()

        with widest_statement(app) as seen:
            report = await retention.sweep(session, {}, dry_run=dry_run)

        assert (report.sessions, report.downloads) == (OBJECTS, OBJECTS)
        remaining = await session.scalar(select(func.count()).select_from(WebSession))
        assert remaining == (OBJECTS if dry_run else 0)
        assert_bounded(seen)
