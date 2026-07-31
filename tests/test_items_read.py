"""Reading items."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_collection, make_item, make_user, tag_item

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


class TestListing:
    async def test_an_empty_library_returns_an_empty_list(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items", headers=AUTH)

        assert response.status_code == 200
        assert response.json() == []
        assert response.headers["Total-Results"] == "0"
        assert response.headers["Last-Modified-Version"] == "10"

    async def test_items_are_returned_in_the_envelope(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="AAAA2345",
            fields={"title": "Moby-Dick", "date": "1851-11-14"},
            creators=[("author", "Herman", "Melville")],
        )

        (body,) = (await client.get("/users/1/items", headers=AUTH)).json()

        assert body["key"] == "AAAA2345"
        assert body["version"] == 1
        assert body["library"]["type"] == "user"
        assert body["library"]["id"] == 1
        assert body["links"]["self"]["href"].endswith("/users/1/items/AAAA2345")
        assert body["meta"]["creatorSummary"] == "Melville"
        assert body["meta"]["parsedDate"] == "1851-11-14"
        assert body["meta"]["numChildren"] == 0
        assert body["data"]["itemType"] == "book"
        assert body["data"]["title"] == "Moby-Dick"
        assert body["data"]["creators"] == [
            {"creatorType": "author", "firstName": "Herman", "lastName": "Melville"}
        ]
        assert body["data"]["tags"] == []
        assert body["data"]["collections"] == []
        assert body["data"]["relations"] == {}
        assert body["data"]["dateAdded"].endswith("Z")

    async def test_trashed_items_are_hidden_by_default(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", deleted=True)

        keys = [i["key"] for i in (await client.get("/users/1/items", headers=AUTH)).json()]

        assert keys == ["AAAA2345"]

    async def test_include_trashed_brings_them_back(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", deleted=True)

        body = (await client.get("/users/1/items?includeTrashed=1", headers=AUTH)).json()

        assert len(body) == 2

    async def test_the_trash_lists_only_trashed_items(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", deleted=True)

        body = (await client.get("/users/1/items/trash", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["BBBB2345"]
        assert body[0]["data"]["deleted"] == 1

    async def test_top_excludes_child_items(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)

        top = (await client.get("/users/1/items/top", headers=AUTH)).json()
        every = (await client.get("/users/1/items", headers=AUTH)).json()

        assert [i["key"] for i in top] == ["AAAA2345"]
        assert len(every) == 2

    async def test_children_lists_an_items_children(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)

        body = (await client.get("/users/1/items/AAAA2345/children", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["BBBB2345"]
        assert body[0]["data"]["parentItem"] == "AAAA2345"
        assert body[0]["links"]["up"]["href"].endswith("/items/AAAA2345")

    async def test_num_children_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()

        assert body["meta"]["numChildren"] == 1


class TestSingleItem:
    async def test_an_item_is_returned_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", fields={"title": "T"})

        response = await client.get("/users/1/items/AAAA2345", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "T"
        assert response.headers["Last-Modified-Version"] == "10"

    async def test_an_unknown_key_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/items/ZZZZ2345", headers=AUTH)).status_code == 404

    async def test_reading_requires_authorisation(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/items")).status_code == 403


class TestFormats:
    async def test_format_keys_returns_one_key_per_line(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345")

        response = await client.get("/users/1/items?format=keys&sort=title", headers=AUTH)

        assert response.headers["content-type"].startswith("text/plain")
        assert sorted(response.text.split("\n")) == ["AAAA2345", "BBBB2345"]

    async def test_format_versions_maps_keys_to_versions(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=7)

        response = await client.get("/users/1/items?format=versions", headers=AUTH)

        assert response.json() == {"AAAA2345": 7}

    async def test_an_unknown_format_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items?format=nope", headers=AUTH)

        assert response.status_code == 400


class TestFiltering:
    async def test_item_key_selects_specific_items(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345")
        await make_item(session, library, key="CCCC2345")

        body = (await client.get("/users/1/items?itemKey=AAAA2345,CCCC2345", headers=AUTH)).json()

        assert sorted(i["key"] for i in body) == ["AAAA2345", "CCCC2345"]

    async def test_more_than_fifty_keys_are_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        keys = ",".join(f"AAAA{n:04d}" for n in range(51))

        response = await client.get(f"/users/1/items?itemKey={keys}", headers=AUTH)

        assert response.status_code == 400

    async def test_item_type_filters(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="book")
        await make_item(session, library, key="BBBB2345", item_type="journalArticle")

        body = (await client.get("/users/1/items?itemType=book", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]

    async def test_item_type_accepts_alternatives(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="book")
        await make_item(session, library, key="BBBB2345", item_type="journalArticle")
        await make_item(session, library, key="CCCC2345", item_type="thesis")

        body = (
            await client.get("/users/1/items?itemType=book || journalArticle", headers=AUTH)
        ).json()

        assert sorted(i["key"] for i in body) == ["AAAA2345", "BBBB2345"]

    async def test_item_type_negation(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="book")
        await make_item(session, library, key="BBBB2345", item_type="note")

        body = (await client.get("/users/1/items?itemType=-note", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]

    async def test_tag_filters(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "fiction")

        body = (await client.get("/users/1/items?tag=fiction", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]

    async def test_repeated_tags_are_combined_with_and(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        both = await make_item(session, library, key="AAAA2345")
        one = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, both, "fiction")
        await tag_item(session, library, both, "classic")
        await tag_item(session, library, one, "fiction")

        body = (await client.get("/users/1/items?tag=fiction&tag=classic", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]

    async def test_tag_alternatives_are_combined_with_or(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await make_item(session, library, key="CCCC2345")
        await tag_item(session, library, one, "fiction")
        await tag_item(session, library, two, "classic")

        body = (await client.get("/users/1/items?tag=fiction || classic", headers=AUTH)).json()

        assert sorted(i["key"] for i in body) == ["AAAA2345", "BBBB2345"]

    async def test_quick_search_matches_title_and_creator(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", fields={"title": "Moby-Dick"})
        await make_item(
            session,
            library,
            key="BBBB2345",
            fields={"title": "Other"},
            creators=[("author", "Herman", "Melville")],
        )
        await make_item(session, library, key="CCCC2345", fields={"title": "Unrelated"})

        moby = (await client.get("/users/1/items?q=moby", headers=AUTH)).json()
        melville = (await client.get("/users/1/items?q=melville", headers=AUTH)).json()

        assert [i["key"] for i in moby] == ["AAAA2345"]
        assert [i["key"] for i in melville] == ["BBBB2345"]

    async def test_quick_search_everything_reaches_other_fields(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session, library, key="AAAA2345", fields={"title": "T", "publisher": "Harper"}
        )

        default = (await client.get("/users/1/items?q=harper", headers=AUTH)).json()
        everything = (
            await client.get("/users/1/items?q=harper&qmode=everything", headers=AUTH)
        ).json()

        assert default == []
        assert [i["key"] for i in everything] == ["AAAA2345"]

    async def test_since_returns_only_newer_objects(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=3)
        await make_item(session, library, key="BBBB2345", version=8)

        body = (await client.get("/users/1/items?since=5", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["BBBB2345"]


class TestSortingAndPaging:
    async def test_sorting_by_title(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", fields={"title": "Zebra"})
        await make_item(session, library, key="BBBB2345", fields={"title": "Apple"})

        body = (await client.get("/users/1/items?sort=title", headers=AUTH)).json()

        assert [i["data"]["title"] for i in body] == ["Apple", "Zebra"]

    async def test_sorting_direction_can_be_reversed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", fields={"title": "Zebra"})
        await make_item(session, library, key="BBBB2345", fields={"title": "Apple"})

        body = (await client.get("/users/1/items?sort=title&direction=desc", headers=AUTH)).json()

        assert [i["data"]["title"] for i in body] == ["Zebra", "Apple"]

    async def test_an_unknown_sort_field_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/items?sort=nope", headers=AUTH)).status_code == 400

    async def test_limit_and_start_page_through_results(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(5):
            await make_item(
                session, library, key=f"AAAA234{index}", fields={"title": f"Item {index}"}
            )

        response = await client.get("/users/1/items?sort=title&limit=2&start=2", headers=AUTH)

        assert [i["data"]["title"] for i in response.json()] == ["Item 2", "Item 3"]
        assert response.headers["Total-Results"] == "5"

    async def test_the_link_header_describes_the_neighbouring_pages(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(5):
            await make_item(
                session, library, key=f"AAAA234{index}", fields={"title": f"Item {index}"}
            )

        link = (
            await client.get("/users/1/items?sort=title&limit=2&start=2", headers=AUTH)
        ).headers["Link"]

        assert 'rel="first"' in link
        assert 'rel="prev"' in link
        assert 'rel="next"' in link
        assert 'rel="last"' in link

    async def test_the_link_header_is_absent_for_a_single_page(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")

        assert "Link" not in (await client.get("/users/1/items", headers=AUTH)).headers

    async def test_the_link_header_preserves_filters(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(5):
            await make_item(session, library, key=f"AAAA234{index}", item_type="book")

        link = (await client.get("/users/1/items?itemType=book&limit=2", headers=AUTH)).headers[
            "Link"
        ]

        assert "itemType=book" in link


class TestConditionalRequests:
    async def test_an_unchanged_library_yields_304(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get(
            "/users/1/items", headers=AUTH | {"If-Modified-Since-Version": "10"}
        )

        assert response.status_code == 304
        assert not response.content

    async def test_an_older_version_yields_the_body(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get(
            "/users/1/items", headers=AUTH | {"If-Modified-Since-Version": "9"}
        )

        assert response.status_code == 200


class TestCollectionScopedItems:
    async def test_items_of_a_collection_are_listed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        inside = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345")
        await make_collection(session, library, key="COLL2345", items=[inside])

        body = (await client.get("/users/1/collections/COLL2345/items", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]

    async def test_top_items_of_a_collection_exclude_children(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA2345")
        child = await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)
        await make_collection(session, library, key="COLL2345", items=[parent, child])

        body = (await client.get("/users/1/collections/COLL2345/items/top", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]

    async def test_an_unknown_collection_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/collections/ZZZZ2345/items", headers=AUTH)

        assert response.status_code == 404
