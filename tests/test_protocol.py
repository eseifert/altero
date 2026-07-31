"""Protocol-level behaviour: version negotiation, CORS and token expiry."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType, WriteToken
from altero.services.auth import get_library
from altero.services.writes import WRITE_TOKEN_LIFETIME_HOURS
from tests.factories import make_api_key, make_user

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


class TestApiVersion:
    async def test_the_version_is_reported_on_every_response(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/itemTypes")

        assert response.headers["Zotero-API-Version"] == "3"

    async def test_asking_for_the_implemented_version_is_fine(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        header = await client.get("/itemTypes", headers={"Zotero-API-Version": "3"})
        parameter = await client.get("/itemTypes?v=3")

        assert header.status_code == 200
        assert parameter.status_code == 200

    @pytest.mark.parametrize("version", ["1", "2", "4"])
    async def test_another_version_is_refused(
        self, client: httpx.AsyncClient, library: Library, version: str
    ) -> None:
        # v1 and v2 clients expect Atom, which this server does not serve.
        response = await client.get("/itemTypes", headers={"Zotero-API-Version": version})

        assert response.status_code == 400
        assert "Invalid API version" in response.text

    async def test_a_disagreeing_header_and_parameter_are_refused(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/itemTypes?v=2", headers={"Zotero-API-Version": "3"})

        assert response.status_code == 400
        assert "does not match" in response.text


class TestCors:
    async def test_protocol_headers_are_exposed_to_browsers(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # A browser cannot read a header that is not named here, and the whole
        # sync protocol lives in headers.
        response = await client.get(
            "/users/1/items", headers=AUTH | {"Origin": "https://example.org"}
        )

        exposed = response.headers["access-control-expose-headers"]
        for name in ("Last-Modified-Version", "Total-Results", "Link", "Backoff"):
            assert name in exposed

    async def test_a_preflight_is_answered(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.options(
            "/users/1/items",
            headers={
                "Origin": "https://example.org",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Zotero-API-Key",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "*"
        assert "POST" in response.headers["access-control-allow-methods"]


class TestWriteTokenExpiry:
    TOKEN = "a" * 32

    async def test_an_expired_token_is_forgotten(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # A token is only worth remembering for as long as a client might
        # retry; after that the same one may be used again.
        await client.post(
            "/users/1/items",
            headers=JSON | {"Zotero-Write-Token": self.TOKEN},
            json=[{"itemType": "book"}],
        )

        stored = await session.scalar(select(WriteToken))
        assert stored is not None
        stored.created = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            hours=WRITE_TOKEN_LIFETIME_HOURS + 1
        )
        await session.commit()

        again = await client.post(
            "/users/1/items",
            headers=JSON | {"Zotero-Write-Token": self.TOKEN},
            json=[{"itemType": "book"}],
        )

        assert again.status_code == 200

    async def test_a_fresh_token_is_still_remembered(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        headers = JSON | {"Zotero-Write-Token": self.TOKEN}
        await client.post("/users/1/items", headers=headers, json=[{"itemType": "book"}])

        again = await client.post("/users/1/items", headers=headers, json=[{"itemType": "book"}])

        assert again.status_code == 412

    async def test_expired_tokens_are_cleared_from_the_table(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        session.add(
            WriteToken(
                library_id=library.id,
                token="b" * 32,
                created=datetime.now(UTC).replace(tzinfo=None)
                - timedelta(hours=WRITE_TOKEN_LIFETIME_HOURS + 1),
            )
        )
        await session.commit()

        await client.post(
            "/users/1/items",
            headers=JSON | {"Zotero-Write-Token": self.TOKEN},
            json=[{"itemType": "book"}],
        )

        remaining = list(await session.scalars(select(WriteToken)))
        assert [token.token for token in remaining] == [self.TOKEN]
