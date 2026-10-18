"""How many SQL statements a request costs.

These are regression guards rather than benchmarks: they assert the *shape* of
the query load, which is what turns into latency once the database is on the
other end of a network. A page that costs one query per item looks fine against
a local SQLite file and falls over against PostgreSQL.
"""

import re
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


#: Recording when a key was last used is amortised -- at most one write per
#: key per minute -- so it is not part of the per-request shape these guards
#: are about, and counting it would make a measurement depend on whether the
#: throttle happened to be warm. That it stays amortised is guarded where it
#: belongs, in tests/test_keyusage.py.
BOOKKEEPING = "UPDATE api_keys SET last_used"


@contextmanager
def capture_sql(app: FastAPI) -> Iterator[list[str]]:
    """Collect every statement the application executes inside the block."""
    statements: list[str] = []
    engine = app.state.database.engine.sync_engine

    def record(_connection: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if statement.strip().startswith(BOOKKEEPING):
            return
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


class TestCollectionListings:
    @pytest.fixture
    async def shelves(self, session: AsyncSession, library: Library) -> Library:
        """Ten collections, each holding an item and each nested under a parent."""
        root = await make_collection(session, library, key="ROOT1111", name="Root")
        for index in range(10):
            item = await make_item(session, library, fields={"title": f"Item {index}"})
            await make_collection(
                session, library, name=f"Shelf {index}", parent=root, items=[item]
            )
        return library

    async def test_a_larger_page_costs_no_more_queries(
        self, app: FastAPI, client: httpx.AsyncClient, shelves: Library
    ) -> None:
        # Two rather than one, so that the small page also holds a nested
        # collection: a page of only top-level collections names no parent and
        # legitimately skips that query.
        with capture_sql(app) as two_collections:
            small = await client.get("/users/1/collections?limit=2", headers=AUTH)
        with capture_sql(app) as ten_collections:
            large = await client.get("/users/1/collections?limit=10", headers=AUTH)

        assert len(small.json()) == 2
        assert len(large.json()) == 10
        assert len(ten_collections) == len(two_collections), (
            f"a page of ten cost {len(ten_collections)} queries "
            f"against {len(two_collections)} for a page of two"
        )

    async def test_the_counts_land_on_the_right_collection(
        self, client: httpx.AsyncClient, shelves: Library
    ) -> None:
        body = (await client.get("/users/1/collections?limit=25", headers=AUTH)).json()
        by_key = {entry["key"]: entry for entry in body}

        root = by_key.pop("ROOT1111")
        assert root["meta"]["numCollections"] == 10
        assert root["meta"]["numItems"] == 0
        assert root["data"]["parentCollection"] is False

        assert len(by_key) == 10
        for entry in by_key.values():
            assert entry["meta"]["numCollections"] == 0
            assert entry["meta"]["numItems"] == 1
            assert entry["data"]["parentCollection"] == "ROOT1111"


class TestUnpaginatedFormats:
    async def test_the_keys_format_is_not_counted_twice(
        self, app: FastAPI, client: httpx.AsyncClient, populated: Library
    ) -> None:
        """An unlimited page is the whole result set, so counting it is wasted work."""
        with capture_sql(app) as statements:
            response = await client.get("/users/1/items?format=keys", headers=AUTH)

        assert response.headers["Total-Results"] == "10"
        assert len(response.text.splitlines()) == 10
        counts = [statement for statement in statements if "count(" in statement.lower()]
        assert counts == [], f"the whole result set was counted as well as fetched: {counts}"

    async def test_an_offset_is_still_reported_in_the_total(
        self, client: httpx.AsyncClient, populated: Library
    ) -> None:
        """The total covers the objects the offset skipped, not just those returned."""
        response = await client.get("/users/1/items?format=keys&start=4", headers=AUTH)

        assert response.headers["Total-Results"] == "10"
        assert len(response.text.splitlines()) == 6

    async def test_the_versions_format_is_not_counted_twice(
        self, app: FastAPI, client: httpx.AsyncClient, populated: Library
    ) -> None:
        with capture_sql(app) as statements:
            response = await client.get("/users/1/items?format=versions", headers=AUTH)

        assert response.headers["Total-Results"] == "10"
        assert len(response.json()) == 10
        assert [statement for statement in statements if "count(" in statement.lower()] == []

    @pytest.mark.parametrize("response_format", ["keys", "versions"])
    async def test_a_key_listing_loads_nothing_but_keys(
        self, app: FastAPI, client: httpx.AsyncClient, populated: Library, response_format: str
    ) -> None:
        """A full sync asks for every key and version, and nothing else of an item.

        Loading each item whole made this the slowest request a desktop client
        sends: every field, creator and relation of the library, to read two
        columns.
        """
        with capture_sql(app) as statements:
            response = await client.get(f"/users/1/items?format={response_format}", headers=AUTH)

        assert response.status_code == 200
        related = [
            statement
            for statement in statements
            if any(
                table in statement for table in ("item_fields", "item_creators", "item_relations")
            )
        ]
        assert related == [], f"a key listing loaded the items themselves: {related}"


class TestExpensiveFilters:
    """A filter that costs more than the page it selects is evaluated once.

    The total then comes from the page itself. Cheap filters keep a separate
    count, which on SQLite is cheaper than the window: evaluating it buffers
    every matching row.
    """

    @pytest.mark.parametrize(
        "path",
        ["/users/1/items?q=Item&limit=3", "/users/1/tags?limit=3", "/users/1/items/tags?limit=3"],
    )
    async def test_the_total_comes_with_the_page(
        self,
        app: FastAPI,
        client: httpx.AsyncClient,
        session: AsyncSession,
        library: Library,
        path: str,
    ) -> None:
        for index in range(5):
            item = await make_item(session, library, fields={"title": f"Item {index}"})
            await tag_item(session, library, item, f"tag {index}")

        with capture_sql(app) as statements:
            response = await client.get(path, headers=AUTH)

        assert len(response.json()) == 3
        assert response.headers["Total-Results"] == "5"
        counts = [s for s in statements if s.lstrip().lower().startswith("select count(")]
        assert counts == [], f"the filter was evaluated twice: {counts}"

    @pytest.mark.parametrize("path", ["/users/1/items?q=Item&start=10", "/users/1/tags?start=10"])
    async def test_a_page_past_the_end_still_reports_the_total(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library, path: str
    ) -> None:
        for index in range(5):
            item = await make_item(session, library, fields={"title": f"Item {index}"})
            await tag_item(session, library, item, f"tag {index}")

        response = await client.get(path, headers=AUTH)

        assert response.json() == []
        assert response.headers["Total-Results"] == "5"


class TestAuthentication:
    """Who is asking costs one statement, and the rest of the request reuses it."""

    async def test_a_key_is_read_with_its_owner(
        self, app: FastAPI, client: httpx.AsyncClient, library: Library
    ) -> None:
        """The key and its owner in one statement, and the overrides in one more.

        Nothing reads a key's per-group overrides off the key itself, so loading
        them with every authenticated request was a statement spent on nothing.
        The owner is the same row the route reads again, and is not asked twice.
        """
        with capture_sql(app) as statements:
            response = await client.get("/keys/current", headers=AUTH)

        assert response.status_code == 200
        assert len(statements) == 2, "\n\n".join(statements)

    async def test_a_browser_session_is_read_with_its_owner(
        self, app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        from altero.services import admin
        from tests.test_web_routes import register

        assert (await register(client)).status_code == 201
        await admin.create_api_key(session, username="ada", name="Desktop")

        with capture_sql(app) as statements:
            response = await client.get("/web/account/keys")

        assert response.status_code == 200
        assert len(response.json()["keys"]) == 1
        reading_users = [s for s in statements if re.search(r"\b(FROM|JOIN) users\b", s)]
        assert len(reading_users) == 1, "\n\n".join(statements)
        assert not [s for s in statements if "api_key_group_access" in s]

    async def test_an_upload_to_a_group_resolves_access_once(
        self, app: FastAPI, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The upload dependency reuses the access the request already has."""
        from tests.factories import make_group

        await make_user(session, user_id=1)
        await make_api_key(session, key=KEY, user_id=1, all_groups_read=True, all_groups_write=True)
        group = await make_group(session, owner_id=1)
        await make_item(session, group, key="AAAA2345", item_type="attachment")
        form = {"md5": "0" * 32, "filename": "a.txt", "filesize": "1", "mtime": "1"}

        with capture_sql(app) as statements:
            response = await client.post(
                f"/groups/{group.owner_id}/items/AAAA2345/file",
                headers=AUTH | {"If-None-Match": "*"},
                data=form,
            )

        assert response.status_code == 200, response.text
        overrides = [s for s in statements if "FROM api_key_group_access" in s]
        policies = [s for s in statements if "FROM groups" in s]
        assert (len(overrides), len(policies)) == (1, 2), "\n\n".join(statements)


class TestDeleting:
    async def _delete(
        self,
        app: FastAPI,
        client: httpx.AsyncClient,
        session: AsyncSession,
        library: Library,
        count: int,
    ) -> list[str]:
        keys = []
        for index in range(count):
            item = await make_item(session, library, fields={"title": f"Item {index}"})
            await make_item(session, library, item_type="note", parent=item)
            await tag_item(session, library, item, f"tag {index}")
            keys.append(item.key)
        version = (await client.get("/users/1/items?limit=1", headers=AUTH)).headers[
            "Last-Modified-Version"
        ]

        with capture_sql(app) as statements:
            response = await client.delete(
                f"/users/1/items?itemKey={','.join(keys)}",
                headers=AUTH | {"If-Unmodified-Since-Version": version},
            )

        assert response.status_code == 204, response.text
        assert (await client.get("/users/1/items", headers=AUTH)).json() == []
        deleted = await client.get(f"/users/1/deleted?since={version}", headers=AUTH)
        assert len(deleted.json()["items"]) == 2 * count
        return statements

    async def test_more_items_cost_no_more_statements(
        self,
        app: FastAPI,
        client: httpx.AsyncClient,
        session: AsyncSession,
        library: Library,
    ) -> None:
        """Deleting is a statement per table, not several per item and its children."""
        few = await self._delete(app, client, session, library, 5)
        many = await self._delete(app, client, session, library, 25)

        assert len(many) == len(few), "\n\n".join(many)


class TestCreating:
    """A new object is one INSERT, not an INSERT and then UPDATEs of the same row."""

    async def test_an_item_is_written_once(
        self, app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="PARENT23")
        children = [
            {"itemType": "note", "note": f"<p>{index}</p>", "parentItem": parent.key}
            for index in range(3)
        ]

        with capture_sql(app) as statements:
            response = await client.post("/users/1/items", headers=AUTH, json=children)

        assert len(response.json()["successful"]) == 3
        assert not [s for s in statements if s.startswith("UPDATE items")], "\n\n".join(statements)

    async def test_a_collection_is_written_once(
        self, app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="PARENT23")
        nested = [{"name": f"Shelf {index}", "parentCollection": "PARENT23"} for index in range(3)]

        with capture_sql(app) as statements:
            response = await client.post("/users/1/collections", headers=AUTH, json=nested)

        assert len(response.json()["successful"]) == 3
        assert not [s for s in statements if s.startswith("UPDATE collections")]

    async def test_the_new_version_is_not_read_back(
        self, app: FastAPI, client: httpx.AsyncClient, library: Library
    ) -> None:
        """RETURNING gave the version, and a personal library records no activity."""
        with capture_sql(app) as statements:
            response = await client.post(
                "/users/1/items", headers=AUTH, json=[{"itemType": "book"}]
            )

        assert response.status_code == 200
        assert not [s for s in statements if s.startswith("SELECT libraries.version")]
        assert not [s for s in statements if "items.sort_title" in s and "FROM items" in s]


class TestFilingAndTagging:
    async def test_a_new_items_tags_and_collections_are_found_together(
        self, app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """One lookup for all of an item's tags and one for its collections.

        A new item has no links yet, so nothing is deleted on the way in.
        """
        other = await make_item(session, library)
        for name in ("a", "b", "c", "d"):
            await tag_item(session, library, other, name)
        await make_collection(session, library, key="SHELF234")
        await make_collection(session, library, key="SHELF567")
        payload = {
            "itemType": "book",
            "tags": [{"tag": name} for name in ("a", "b", "c", "d")],
            "collections": ["SHELF234", "SHELF567"],
        }

        with capture_sql(app) as statements:
            response = await client.post("/users/1/items", headers=AUTH, json=[payload])

        data = response.json()["successful"]["0"]["data"]
        assert (len(data["tags"]), len(data["collections"])) == (4, 2)
        tag_lookups = [s for s in statements if re.match(r"SELECT tags\.id\b", s)]
        filing_lookups = [s for s in statements if re.match(r"SELECT collections\.(id|\"key\")", s)]
        assert (len(tag_lookups), len(filing_lookups)) == (1, 1), "\n\n".join(statements)
        assert not [s for s in statements if s.startswith("DELETE")]

    async def test_changing_one_tag_rewrites_one_link(
        self, app: FastAPI, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="TAGGED23", version=5)
        for name in ("a", "b"):
            await tag_item(session, library, item, name)

        with capture_sql(app) as statements:
            response = await client.post(
                "/users/1/items",
                headers=AUTH,
                json=[{"key": "TAGGED23", "version": 5, "tags": [{"tag": "a"}, {"tag": "c"}]}],
            )

        data = response.json()["successful"]["0"]["data"]
        assert sorted(tag["tag"] for tag in data["tags"]) == ["a", "c"]
        removed = [s for s in statements if s.startswith("DELETE FROM item_tags")]
        added = [s for s in statements if s.startswith("INSERT INTO item_tags")]
        assert (len(removed), len(added)) == (1, 1), "\n\n".join(statements)
