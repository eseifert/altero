"""Writing collections, saved searches and tags, and the delete log."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import (
    make_api_key,
    make_collection,
    make_item,
    make_search,
    make_user,
    tag_item,
)

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}
VERSIONED = AUTH | {"If-Unmodified-Since-Version": "10"}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestCollectionWrites:
    async def test_a_collection_is_created(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/collections", headers=JSON, json=[{"name": "Fiction"}]
        )

        assert response.status_code == 200
        created = response.json()["successful"]["0"]
        assert created["data"]["name"] == "Fiction"
        assert created["data"]["parentCollection"] is False
        assert created["version"] == 11

    async def test_a_nested_collection_is_created(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", name="Parent")

        body = (
            await client.post(
                "/users/1/collections",
                headers=JSON,
                json=[{"name": "Child", "parentCollection": "AAAA2345"}],
            )
        ).json()

        assert body["successful"]["0"]["data"]["parentCollection"] == "AAAA2345"

    async def test_a_collection_without_a_name_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (await client.post("/users/1/collections", headers=JSON, json=[{}])).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_an_unknown_parent_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/collections",
                headers=JSON,
                json=[{"name": "Child", "parentCollection": "ZZZZ2345"}],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 404

    async def test_a_collection_is_replaced(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", name="Old", version=10)

        response = await client.put(
            "/users/1/collections/AAAA2345",
            headers=JSON,
            json={"name": "New", "version": 10},
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).json()
        assert body["data"]["name"] == "New"

    async def test_replacing_with_a_stale_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", version=10)

        response = await client.put(
            "/users/1/collections/AAAA2345", headers=JSON, json={"name": "New", "version": 2}
        )

        assert response.status_code == 412

    async def test_a_collection_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")

        response = await client.delete("/users/1/collections/AAAA2345", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).status_code == 404

    async def test_deleting_promotes_nested_collections(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        grandparent = await make_collection(session, library, key="AAAA2345")
        parent = await make_collection(session, library, key="BBBB2345", parent=grandparent)
        await make_collection(session, library, key="CCCC2345", parent=parent)

        await client.delete("/users/1/collections/BBBB2345", headers=VERSIONED)

        child = (await client.get("/users/1/collections/CCCC2345", headers=AUTH)).json()
        assert child["data"]["parentCollection"] == "AAAA2345"

    async def test_deleting_without_a_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")

        assert (
            await client.delete("/users/1/collections/AAAA2345", headers=AUTH)
        ).status_code == 428

    async def test_several_collections_are_deleted_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")
        await make_collection(session, library, key="BBBB2345")

        response = await client.delete(
            "/users/1/collections?collectionKey=AAAA2345,BBBB2345", headers=VERSIONED
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/collections", headers=AUTH)).json() == []


class TestSearchWrites:
    async def test_a_search_is_created(self, client: httpx.AsyncClient, library: Library) -> None:
        response = await client.post(
            "/users/1/searches",
            headers=JSON,
            json=[
                {
                    "name": "Whales",
                    "conditions": [
                        {"condition": "title", "operator": "contains", "value": "whale"}
                    ],
                }
            ],
        )

        assert response.status_code == 200
        created = response.json()["successful"]["0"]
        assert created["data"]["name"] == "Whales"
        assert created["data"]["conditions"][0]["value"] == "whale"

    async def test_a_search_without_conditions_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post("/users/1/searches", headers=JSON, json=[{"name": "Empty"}])
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_a_search_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="AAAA2345")

        response = await client.delete("/users/1/searches/AAAA2345", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/searches/AAAA2345", headers=AUTH)).status_code == 404

    async def test_several_searches_are_deleted_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="AAAA2345")
        await make_search(session, library, key="BBBB2345")

        response = await client.delete(
            "/users/1/searches?searchKey=AAAA2345,BBBB2345", headers=VERSIONED
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/searches", headers=AUTH)).json() == []


class TestTagWrites:
    async def test_a_tag_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        response = await client.delete("/users/1/tags?tag=fiction", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []

    async def test_deleting_a_tag_leaves_the_item(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        await client.delete("/users/1/tags?tag=fiction", headers=VERSIONED)

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["tags"] == []

    async def test_several_tags_are_deleted_with_alternatives(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await tag_item(session, library, item, "classic")

        response = await client.delete("/users/1/tags?tag=fiction || classic", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []

    async def test_both_types_of_a_name_are_removed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "shared", tag_type=0)
        await tag_item(session, library, two, "shared", tag_type=1)

        await client.delete("/users/1/tags?tag=shared", headers=VERSIONED)

        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []

    async def test_deleting_without_a_tag_deletes_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The desktop client sends its tag names as `tags`, which its own
        # parameter filter then drops, so the request arrives bare. Upstream
        # answers 204 having done nothing, and the client accepts only 204 or
        # 412 here — a 400 aborts the sync.
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        response = await client.delete("/users/1/tags", headers=VERSIONED)

        assert response.status_code == 204
        assert [t["tag"] for t in (await client.get("/users/1/tags", headers=AUTH)).json()] == [
            "fiction"
        ]

    async def test_the_plural_parameter_is_also_accepted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Should the client ever stop dropping it, `tags` means the same thing,
        # and its values are joined with a bare `||` rather than a spaced one.
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await tag_item(session, library, item, "classic")

        response = await client.delete("/users/1/tags?tags=fiction||classic", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []


class TestDeleteLog:
    async def test_since_is_required(self, client: httpx.AsyncClient, library: Library) -> None:
        assert (await client.get("/users/1/deleted", headers=AUTH)).status_code == 400

    async def test_an_empty_log_reports_every_group(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (await client.get("/users/1/deleted?since=0", headers=AUTH)).json()

        assert body == {
            "collections": [],
            "items": [],
            "searches": [],
            "settings": [],
            "tags": [],
        }

    async def test_a_deleted_item_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await client.delete("/users/1/items/AAAA2345", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["items"] == ["AAAA2345"]

    async def test_a_deleted_collection_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")
        await client.delete("/users/1/collections/AAAA2345", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["collections"] == ["AAAA2345"]

    async def test_a_deleted_search_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="AAAA2345")
        await client.delete("/users/1/searches/AAAA2345", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["searches"] == ["AAAA2345"]

    async def test_a_deleted_tag_is_reported_by_name(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await client.delete("/users/1/tags?tag=fiction", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["tags"] == ["fiction"]

    async def test_older_deletions_are_not_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        response = await client.delete("/users/1/items/AAAA2345", headers=VERSIONED)
        version = int(response.headers["Last-Modified-Version"])

        body = (await client.get(f"/users/1/deleted?since={version}", headers=AUTH)).json()

        assert body["items"] == []

    async def test_deleting_the_same_key_twice_yields_one_entry(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The dataserver keys this table on (library, type, key), so a repeat
        # moves the existing row forward instead of adding a second one.
        await make_item(session, library, key="AAAA2345")
        await client.delete("/users/1/items/AAAA2345", headers=VERSIONED)

        await make_item(session, library, key="AAAA2345")
        latest = (await client.get("/users/1/items", headers=AUTH)).headers["Last-Modified-Version"]
        await client.delete(
            "/users/1/items/AAAA2345",
            headers=AUTH | {"If-Unmodified-Since-Version": latest},
        )

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["items"] == ["AAAA2345"]
