"""How many SQL statements a request costs.

These are regression guards rather than benchmarks: they assert the *shape* of
the query load, which is what turns into latency once the database is on the
other end of a network. A page that costs one query per item looks fine against
a local SQLite file and falls over against PostgreSQL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_collection, make_item, make_user, tag_item

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}


@contextmanager
def capture_sql(app: FastAPI) -> Iterator[list[str]]:
    """Collect every statement the application executes inside the block."""
    statements: list[str] = []
    engine = app.state.database.engine.sync_engine

    def record(_connection: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


@pytest.fixture
async def populated(session: AsyncSession, library: Library) -> Library:
    """A library of ten items, each tagged and each in a collection."""
    items = [
        await make_item(session, library, fields={"title": f"Item {index}"}) for index in range(10)
    ]
    for item in items:
        await tag_item(session, library, item, "read")
    await make_collection(session, library, name="Shelf", items=items)
    return library


class TestItemListings:
    async def test_a_larger_page_costs_no_more_queries(
        self, app: FastAPI, client: httpx.AsyncClient, populated: Library
    ) -> None:
        """The related data of a page is fetched per page, not per item."""
        with capture_sql(app) as one_item:
            small = await client.get("/users/1/items?limit=1", headers=AUTH)
        with capture_sql(app) as ten_items:
            large = await client.get("/users/1/items?limit=10", headers=AUTH)

        assert len(small.json()) == 1
        assert len(large.json()) == 10
        assert len(ten_items) == len(one_item), (
            f"a page of ten cost {len(ten_items)} queries against {len(one_item)} for a page of one"
        )

    async def test_the_envelope_survives_batching(
        self, client: httpx.AsyncClient, populated: Library
    ) -> None:
        """The related data still lands on the right item once fetched in bulk."""
        body = (await client.get("/users/1/items?limit=10", headers=AUTH)).json()

        assert len(body) == 10
        for entry in body:
            assert entry["data"]["tags"] == [{"tag": "read"}]
            assert len(entry["data"]["collections"]) == 1
            assert entry["meta"]["numChildren"] == 0

    async def test_children_are_counted_per_parent(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Library
    ) -> None:
        """A batched count must not spread one parent's children over the page."""
        parent = await make_item(session, library, key="AAAA1111")
        await make_item(session, library, item_type="note", parent=parent)
        await make_item(session, library, item_type="note", parent=parent)
        await make_item(session, library, key="BBBB2222")

        body = (await client.get("/users/1/items?limit=10", headers=AUTH)).json()
        children = {entry["key"]: entry["meta"]["numChildren"] for entry in body}

        assert children["AAAA1111"] == 2
        assert children["BBBB2222"] == 0

    async def test_a_child_still_names_its_parent(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA1111")
        await make_item(session, library, key="CCCC3333", item_type="note", parent=parent)

        body = (await client.get("/users/1/items?limit=10", headers=AUTH)).json()
        parents = {entry["key"]: entry["data"].get("parentItem") for entry in body}

        assert parents["CCCC3333"] == "AAAA1111"
        assert parents["AAAA1111"] is None
