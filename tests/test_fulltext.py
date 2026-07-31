"""Full-text content of attachments."""

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


class TestStoringContent:
    async def test_content_round_trips(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        put = await client.put(
            "/users/1/items/AAAA2345/fulltext",
            headers=JSON,
            json={"content": "Call me Ishmael.", "indexedPages": 3, "totalPages": 10},
        )

        assert put.status_code == 204
        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert body == {
            "content": "Call me Ishmael.",
            "indexedPages": 3,
            "totalPages": 10,
        }

    async def test_statistics_the_client_omits_are_not_invented(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        await client.put(
            "/users/1/items/AAAA2345/fulltext",
            headers=JSON,
            json={"content": "text", "indexedChars": 4, "totalChars": 4},
        )

        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert set(body) == {"content", "indexedChars", "totalChars"}

    async def test_content_can_be_replaced(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "first"}
        )
        await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "second"}
        )

        body = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert body["content"] == "second"

    async def test_storing_advances_the_library_version(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "t"}
        )

        assert response.headers["Last-Modified-Version"] == "11"

    async def test_a_body_without_content_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.put(
            "/users/1/items/AAAA2345/fulltext", headers=JSON, json={"indexedPages": 1}
        )

        assert response.status_code == 400

    async def test_an_unknown_item_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.put(
            "/users/1/items/ZZZZ2345/fulltext", headers=JSON, json={"content": "t"}
        )

        assert response.status_code == 404

    async def test_writing_requires_write_permission(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=2, username="reader")
        await make_api_key(session, key="READONLY", user_id=2, library_write=False)
        library = await get_library(session, LibraryType.USER, 2)
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.put(
            "/users/2/items/AAAA2345/fulltext",
            headers={"Zotero-API-Key": "READONLY"},
            json={"content": "t"},
        )

        assert response.status_code == 403


class TestReading:
    async def test_an_item_without_content_is_a_404(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)

        assert response.status_code == 404


class TestVersionIndex:
    async def test_the_index_is_empty_to_begin_with(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/fulltext", headers=AUTH)).json() == {}

    async def test_the_index_reports_every_indexed_item(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")
        await client.put("/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "a"})
        await client.put("/users/1/items/BBBB2345/fulltext", headers=JSON, json={"content": "b"})

        body = (await client.get("/users/1/fulltext", headers=AUTH)).json()

        assert body == {"AAAA2345": 11, "BBBB2345": 12}

    async def test_since_filters_the_index(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")
        await client.put("/users/1/items/AAAA2345/fulltext", headers=JSON, json={"content": "a"})
        await client.put("/users/1/items/BBBB2345/fulltext", headers=JSON, json={"content": "b"})

        body = (await client.get("/users/1/fulltext?since=11", headers=AUTH)).json()

        assert body == {"BBBB2345": 12}

    async def test_an_unreadable_since_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/fulltext?since=abc", headers=AUTH)).status_code == 400
