"""``/users/<id>/publications`` — the public view of My Publications.

Read anonymously, which is the point of it: upstream's own test suite defaults
to ``API::useAPIKey("")`` for the whole file and expects 200. Only items flagged
``inPublications`` appear, and only ``items`` exists -- ``publications/collections``
and ``publications/searches`` answer 404.

There is no group equivalent. My Publications belongs to a person.
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


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


@pytest.fixture
async def published(session: AsyncSession, library: Library) -> dict[str, Any]:
    """One published item, one private one, and a child of the published one."""
    public = await make_item(
        session, library, key="PUBLIC01", fields={"title": "Published"}, in_publications=True
    )
    await make_item(session, library, key="PRIVATE1", fields={"title": "Private"})
    await make_item(
        session,
        library,
        key="CHILD001",
        item_type="note",
        parent=public,
        fields={"note": "A note"},
        in_publications=True,
    )
    return {"public": "PUBLIC01", "private": "PRIVATE1", "child": "CHILD001"}


class TestReadingWithoutAKey:
    async def test_the_listing_is_anonymous(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        response = await client.get("/users/1/publications/items")

        assert response.status_code == 200
        assert response.headers["Last-Modified-Version"] == "10"

    async def test_only_published_items_appear(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        listing = await client.get("/users/1/publications/items")

        keys = {entry["key"] for entry in listing.json()}
        assert published["private"] not in keys
        assert published["public"] in keys

    async def test_an_empty_publications_list_is_not_an_error(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/publications/items")

        assert response.status_code == 200
        assert response.json() == []

    async def test_a_key_may_still_be_supplied(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        response = await client.get("/users/1/publications/items", headers=AUTH)

        assert response.status_code == 200

    async def test_top_excludes_children(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        listing = await client.get("/users/1/publications/items/top")

        assert [entry["key"] for entry in listing.json()] == [published["public"]]

    async def test_one_item_can_be_fetched(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        response = await client.get(f"/users/1/publications/items/{published['public']}")

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "Published"

    async def test_a_private_item_is_not_reachable_by_key(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        # The listing hiding it would be no use if the key still fetched it.
        response = await client.get(f"/users/1/publications/items/{published['private']}")

        assert response.status_code == 404

    async def test_the_sync_formats_work(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        versions = await client.get("/users/1/publications/items?format=versions")

        assert set(versions.json()) == {published["public"], published["child"]}


class TestWhatIsNotThere:
    @pytest.mark.parametrize("path", ["collections", "searches"])
    async def test_only_items_exist(
        self, client: httpx.AsyncClient, library: Library, path: str
    ) -> None:
        response = await client.get(f"/users/1/publications/{path}")

        assert response.status_code == 404

    async def test_writing_is_refused(self, client: httpx.AsyncClient, library: Library) -> None:
        # A public list is public to read, not to add to.
        response = await client.post(
            "/users/1/publications/items",
            headers=JSON,
            json=[{"itemType": "book", "title": "Dune"}],
        )

        assert response.status_code == 403

    async def test_a_group_has_no_publications(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/groups/2/publications/items")

        assert response.status_code == 404
