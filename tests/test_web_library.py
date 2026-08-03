"""Reading a library through the web interface's own endpoints."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import admin
from tests.test_web_routes import csrf_headers, register


class TestLibraries:
    async def test_the_personal_library_is_listed(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.get("/web/libraries")

        assert response.status_code == 200
        assert [library["type"] for library in response.json()] == ["user"]

    async def test_it_needs_a_session(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/libraries")).status_code == 401

    async def test_another_user_s_library_is_not_listed(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        await admin.create_user(session, username="grace")

        libraries = (await client.get("/web/libraries")).json()

        assert all(library["ownerId"] == 1 for library in libraries)


class TestItems:
    async def test_an_empty_library_lists_nothing_and_says_so(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

        response = await client.get(f"/web/libraries/{library_id}/items")

        assert response.status_code == 200
        assert response.json() == {"total": 0, "libraryVersion": 0, "items": []}

    async def test_items_come_back_in_the_v3_shape(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Same serialiser as the sync API, so there is one idea of an item."""
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="seed")
        await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "book", "title": "Structure and Interpretation"}],
        )
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

        body = (await client.get(f"/web/libraries/{library_id}/items")).json()

        assert body["total"] == 1
        assert body["items"][0]["data"]["title"] == "Structure and Interpretation"
        assert body["items"][0]["data"]["itemType"] == "book"
        assert "key" in body["items"][0]

    async def test_another_user_s_library_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await admin.create_user(session, username="grace")
        from sqlalchemy import select

        from altero.models import Library, LibraryType

        other = await session.scalar(
            select(Library).where(Library.type == LibraryType.USER, Library.owner_id == grace.id)
        )
        assert other is not None

        response = await client.get(f"/web/libraries/{other.id}/items")

        assert response.status_code == 403

    async def test_a_missing_library_is_404(self, client: httpx.AsyncClient) -> None:
        await register(client)

        assert (await client.get("/web/libraries/9999/items")).status_code == 404

    async def test_an_absurd_limit_is_refused_rather_than_served(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

        response = await client.get(f"/web/libraries/{library_id}/items?limit=10000")

        assert response.status_code == 400

    async def test_signing_out_ends_access_to_the_library(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        assert (await client.get("/web/libraries")).status_code == 401
