"""Reading collections, saved searches and tags."""

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


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestCollections:
    async def test_collections_are_returned_in_the_envelope(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="COLL2345", name="Fiction")

        (body,) = (await client.get("/users/1/collections", headers=AUTH)).json()

        assert body["key"] == "COLL2345"
        assert body["data"]["name"] == "Fiction"
        assert body["data"]["parentCollection"] is False
        assert body["meta"] == {"numCollections": 0, "numItems": 0}
        assert body["links"]["self"]["href"].endswith("/users/1/collections/COLL2345")

    async def test_a_nested_collection_names_its_parent(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_collection(session, library, key="AAAA2345", name="Parent")
        await make_collection(session, library, key="BBBB2345", name="Child", parent=parent)

        body = (await client.get("/users/1/collections/BBBB2345", headers=AUTH)).json()

        assert body["data"]["parentCollection"] == "AAAA2345"
        assert body["links"]["up"]["href"].endswith("/collections/AAAA2345")

    async def test_top_excludes_nested_collections(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_collection(session, library, key="AAAA2345")
        await make_collection(session, library, key="BBBB2345", parent=parent)

        top = (await client.get("/users/1/collections/top", headers=AUTH)).json()

        assert [c["key"] for c in top] == ["AAAA2345"]

    async def test_subcollections_are_listed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_collection(session, library, key="AAAA2345")
        await make_collection(session, library, key="BBBB2345", parent=parent)

        body = (await client.get("/users/1/collections/AAAA2345/collections", headers=AUTH)).json()

        assert [c["key"] for c in body] == ["BBBB2345"]

    async def test_counts_are_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="ITEM2345")
        parent = await make_collection(session, library, key="AAAA2345", items=[item])
        await make_collection(session, library, key="BBBB2345", parent=parent)

        body = (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).json()

        assert body["meta"] == {"numCollections": 1, "numItems": 1}

    async def test_collections_sort_by_name_by_default(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", name="Zebra")
        await make_collection(session, library, key="BBBB2345", name="Apple")

        body = (await client.get("/users/1/collections", headers=AUTH)).json()

        assert [c["data"]["name"] for c in body] == ["Apple", "Zebra"]

    async def test_an_unknown_collection_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/collections/ZZZZ2345", headers=AUTH)

        assert response.status_code == 404

    async def test_format_keys_is_supported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="COLL2345")

        response = await client.get("/users/1/collections?format=keys", headers=AUTH)

        assert response.text == "COLL2345"

    async def test_since_filters_collections(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", version=3)
        await make_collection(session, library, key="BBBB2345", version=8)

        body = (await client.get("/users/1/collections?since=5", headers=AUTH)).json()

        assert [c["key"] for c in body] == ["BBBB2345"]


class TestSearches:
    async def test_searches_are_returned_with_their_conditions(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(
            session,
            library,
            key="SRCH2345",
            name="Recent",
            conditions=[("title", "contains", "whale")],
        )

        (body,) = (await client.get("/users/1/searches", headers=AUTH)).json()

        assert body["key"] == "SRCH2345"
        assert body["data"]["name"] == "Recent"
        assert body["data"]["conditions"] == [
            {"condition": "title", "operator": "contains", "value": "whale"}
        ]

    async def test_a_search_is_returned_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="SRCH2345", name="Recent")

        response = await client.get("/users/1/searches/SRCH2345", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Recent"

    async def test_an_unknown_search_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/searches/ZZZZ2345", headers=AUTH)).status_code == 404


class TestTags:
    async def test_tags_are_returned_with_their_counts(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "fiction")
        await tag_item(session, library, two, "fiction")

        (body,) = (await client.get("/users/1/tags", headers=AUTH)).json()

        assert body["tag"] == "fiction"
        assert body["meta"] == {"type": 0, "numItems": 2}

    async def test_automatic_tags_report_their_type(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "auto", tag_type=1)

        (body,) = (await client.get("/users/1/tags", headers=AUTH)).json()

        assert body["meta"]["type"] == 1

    async def test_a_tag_is_returned_by_name(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        response = await client.get("/users/1/tags/fiction", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["tag"] == "fiction"

    async def test_an_unknown_tag_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/tags/nope", headers=AUTH)).status_code == 404

    async def test_tags_of_one_item_are_listed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "fiction")
        await tag_item(session, library, two, "history")

        body = (await client.get("/users/1/items/AAAA2345/tags", headers=AUTH)).json()

        assert [t["tag"] for t in body] == ["fiction"]

    async def test_a_quick_search_filters_tag_names(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await tag_item(session, library, item, "history")

        contains = (await client.get("/users/1/tags?q=ist", headers=AUTH)).json()
        starts = (await client.get("/users/1/tags?q=ist&qmode=startsWith", headers=AUTH)).json()

        assert [t["tag"] for t in contains] == ["history"]
        assert starts == []

    async def test_tags_can_be_sorted_by_item_count(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "rare")
        await tag_item(session, library, one, "common")
        await tag_item(session, library, two, "common")

        body = (await client.get("/users/1/tags?sort=numItems&direction=desc", headers=AUTH)).json()

        assert [t["tag"] for t in body] == ["common", "rare"]

    async def test_an_item_carries_its_tags_and_collections(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await tag_item(session, library, item, "auto", tag_type=1)
        await make_collection(session, library, key="COLL2345", items=[item])

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()

        assert body["data"]["tags"] == [{"tag": "auto", "type": 1}, {"tag": "fiction"}]
        assert body["data"]["collections"] == ["COLL2345"]


class TestScopedTags:
    """Tags can be listed against any of the item scopes."""

    async def test_tags_of_a_collection_are_listed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        inside = await make_item(session, library, key="AAAA2345")
        outside = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, inside, "inside")
        await tag_item(session, library, outside, "outside")
        await make_collection(session, library, key="COLL2345", items=[inside])

        body = (await client.get("/users/1/collections/COLL2345/tags", headers=AUTH)).json()

        assert [t["tag"] for t in body] == ["inside"]

    async def test_tags_of_a_collections_items_are_listed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        inside = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, inside, "inside")
        await make_collection(session, library, key="COLL2345", items=[inside])

        body = (await client.get("/users/1/collections/COLL2345/items/tags", headers=AUTH)).json()

        assert [t["tag"] for t in body] == ["inside"]

    async def test_top_level_tags_exclude_child_items(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA2345")
        child = await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)
        await tag_item(session, library, parent, "onparent")
        await tag_item(session, library, child, "onchild")

        top = (await client.get("/users/1/items/top/tags", headers=AUTH)).json()
        every = (await client.get("/users/1/items/tags", headers=AUTH)).json()

        assert [t["tag"] for t in top] == ["onparent"]
        assert sorted(t["tag"] for t in every) == ["onchild", "onparent"]

    async def test_trash_tags_cover_only_trashed_items(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        live = await make_item(session, library, key="AAAA2345")
        trashed = await make_item(session, library, key="BBBB2345", deleted=True)
        await tag_item(session, library, live, "live")
        await tag_item(session, library, trashed, "gone")

        body = (await client.get("/users/1/items/trash/tags", headers=AUTH)).json()

        assert [t["tag"] for t in body] == ["gone"]

    async def test_top_and_trash_are_not_read_as_item_keys(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # `/items/top/tags` must not be routed as item key "top".
        for scope in ("top", "trash"):
            response = await client.get(f"/users/1/items/{scope}/tags", headers=AUTH)
            assert response.status_code == 200, scope

    async def test_a_scoped_listing_still_counts_across_the_library(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "shared")
        await tag_item(session, library, two, "shared")
        await make_collection(session, library, key="COLL2345", items=[one])

        body = (await client.get("/users/1/collections/COLL2345/tags", headers=AUTH)).json()

        assert [t["tag"] for t in body] == ["shared"]
        assert body[0]["meta"]["numItems"] == 1
