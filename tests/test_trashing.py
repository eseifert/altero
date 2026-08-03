"""Trashing a collection or a saved search.

Zotero trashes a collection by setting ``deleted`` on the object rather than by
deleting it, and syncs that like any other property:
``if (isset($json->deleted) || !$partialUpdate) { $collection->deleted = ... }``
in ``Zotero_Collections::updateFromJSON``, and the same in ``Searches``.

altero could report the flag -- the column exists and the serializer emits it --
but nothing ever set it, so a collection the user moved to the trash stayed
untrashed on the server and in every other client.

Trashed objects stay in the listings, carrying ``deleted: 1``. That is not a
detail: the client has no ``includeTrashed`` parameter for collections, so a
listing that hid them would tell it the collection had been removed outright.
Upstream has no trash filter in its collection queries, and its
``numCollections`` is a bare ``SELECT COUNT(*) ... WHERE parentCollectionID=?``.
``numItems`` does exclude trashed items, and still does here.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}

SEARCH = {
    "name": "Recent",
    "conditions": [{"condition": "title", "operator": "contains", "value": "Dune"}],
}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


async def post(
    client: httpx.AsyncClient, path: str, payload: list[dict[str, Any]]
) -> httpx.Response:
    return await client.post(path, headers=JSON, json=payload)


async def make_one(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    created = await post(client, path, [payload])
    data: dict[str, Any] = created.json()["successful"]["0"]["data"]
    return data


class TestTrashingACollection:
    async def test_the_flag_is_stored(self, client: httpx.AsyncClient, library: Library) -> None:
        stored = await make_one(client, "/users/1/collections", {"name": "Fiction"})

        await post(client, "/users/1/collections", [{**stored, "deleted": 1}])

        fetched = await client.get(f"/users/1/collections/{stored['key']}", headers=AUTH)
        assert fetched.json()["data"]["deleted"] == 1

    async def test_a_trashed_collection_stays_in_the_listing(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await make_one(client, "/users/1/collections", {"name": "Fiction"})
        await post(client, "/users/1/collections", [{**stored, "deleted": 1}])

        listing = await client.get("/users/1/collections", headers=AUTH)

        assert [entry["key"] for entry in listing.json()] == [stored["key"]]

    async def test_a_trashed_collection_stays_in_format_versions(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # This is how a syncing client learns anything at all. Dropping the
        # collection here would read as "removed", not "trashed".
        stored = await make_one(client, "/users/1/collections", {"name": "Fiction"})
        await post(client, "/users/1/collections", [{**stored, "deleted": 1}])

        versions = await client.get(
            "/users/1/collections", params={"format": "versions"}, headers=AUTH
        )

        assert stored["key"] in versions.json()

    async def test_it_can_be_taken_out_of_the_trash(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await make_one(client, "/users/1/collections", {"name": "Fiction"})
        trashed = await post(client, "/users/1/collections", [{**stored, "deleted": 1}])
        current = trashed.json()["successful"]["0"]["data"]
        del current["deleted"]

        await post(client, "/users/1/collections", [current])

        fetched = await client.get(f"/users/1/collections/{stored['key']}", headers=AUTH)
        assert "deleted" not in fetched.json()["data"]

    async def test_a_trashed_subcollection_still_counts(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # Upstream counts with a bare SELECT COUNT(*) and no trash filter.
        parent = await make_one(client, "/users/1/collections", {"name": "Parent"})
        child = await make_one(
            client, "/users/1/collections", {"name": "Child", "parentCollection": parent["key"]}
        )
        await post(client, "/users/1/collections", [{**child, "deleted": 1}])

        fetched = await client.get(f"/users/1/collections/{parent['key']}", headers=AUTH)

        assert fetched.json()["meta"]["numCollections"] == 1

    async def test_a_trashed_item_still_does_not_count(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # numItems does filter upstream, and must go on doing so here.
        collection = await make_one(client, "/users/1/collections", {"name": "Fiction"})
        item = await make_one(
            client,
            "/users/1/items",
            {"itemType": "book", "title": "Dune", "collections": [collection["key"]]},
        )
        await post(client, "/users/1/items", [{**item, "deleted": 1}])

        fetched = await client.get(f"/users/1/collections/{collection['key']}", headers=AUTH)

        assert fetched.json()["meta"]["numItems"] == 0

    async def test_trashing_is_not_an_unchanged_write(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await make_one(client, "/users/1/collections", {"name": "Fiction"})

        again = await post(client, "/users/1/collections", [{**stored, "deleted": 1}])

        assert again.json()["unchanged"] == {}
        assert set(again.json()["successful"]) == {"0"}

    async def test_a_non_boolean_flag_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await post(
            client, "/users/1/collections", [{"name": "Fiction", "deleted": "yes"}]
        )

        assert response.json()["failed"]["0"]["code"] == 400


class TestTrashingASearch:
    async def test_the_flag_is_stored(self, client: httpx.AsyncClient, library: Library) -> None:
        stored = await make_one(client, "/users/1/searches", SEARCH)

        await post(client, "/users/1/searches", [{**stored, "deleted": 1}])

        fetched = await client.get(f"/users/1/searches/{stored['key']}", headers=AUTH)
        assert fetched.json()["data"]["deleted"] == 1

    async def test_a_trashed_search_stays_in_the_listing(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await make_one(client, "/users/1/searches", SEARCH)
        await post(client, "/users/1/searches", [{**stored, "deleted": 1}])

        listing = await client.get("/users/1/searches", headers=AUTH)

        assert [entry["key"] for entry in listing.json()] == [stored["key"]]

    async def test_it_can_be_taken_out_of_the_trash(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await make_one(client, "/users/1/searches", SEARCH)
        trashed = await post(client, "/users/1/searches", [{**stored, "deleted": 1}])
        current = trashed.json()["successful"]["0"]["data"]
        del current["deleted"]

        await post(client, "/users/1/searches", [current])

        fetched = await client.get(f"/users/1/searches/{stored['key']}", headers=AUTH)
        assert "deleted" not in fetched.json()["data"]

    async def test_trashing_is_not_an_unchanged_write(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await make_one(client, "/users/1/searches", SEARCH)

        again = await post(client, "/users/1/searches", [{**stored, "deleted": 1}])

        assert again.json()["unchanged"] == {}


class TestTrashedItemsAreUnaffected:
    async def test_the_items_listing_still_hides_the_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Items are the one type with real trash semantics upstream -- a
        # separate endpoint and an includeTrashed parameter -- so nothing here
        # may change for them.
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", deleted=True)

        listing = await client.get("/users/1/items", headers=AUTH)

        assert [entry["key"] for entry in listing.json()] == ["AAAA2345"]

    async def test_the_trash_endpoint_still_shows_them(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="BBBB2345", deleted=True)

        trash = await client.get("/users/1/items/trash", headers=AUTH)

        assert [entry["key"] for entry in trash.json()] == ["BBBB2345"]
