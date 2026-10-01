"""The original API client must accept altero's sync watermark and response body."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.factories import make_api_key, make_item, make_user

from altero.models import Library, LibraryType
from tools.compatibility.client import CompatibilityError, ZoteroClient

KEY = "HeaderKeyHeaderKeyHeader"
AUTH = {"Zotero-API-Key": KEY}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session)
    await make_api_key(session, key=KEY)
    library = await session.scalar(select(Library).where(Library.type == LibraryType.USER))
    assert library is not None
    library.version = 7
    await make_item(session, library, key="ABCDEFGH", version=7)
    return library


def captured(response: httpx.Response) -> dict:
    return {
        "status": response.status_code,
        "headers": dict(response.headers),
        "text": response.text,
    }


async def test_a_version_listing_is_accepted_by_the_desktop_client(
    library: Library, client: httpx.AsyncClient, zotero_client: ZoteroClient
) -> None:
    response = await client.get("/users/1/items?format=versions", headers=AUTH)
    assert response.status_code == 200

    result = zotero_client.call(
        "sync_versions", ["user", 1, "item", {}], fixtures=captured(response)
    )

    assert result["value"] == {"libraryVersion": "7", "versions": {"ABCDEFGH": 7}}
    assert result["requests"][0]["params"]["includeTrashed"] == 1


async def test_the_desktop_client_rejects_a_missing_watermark(
    library: Library, client: httpx.AsyncClient, zotero_client: ZoteroClient
) -> None:
    response = await client.get("/users/1/items?format=versions", headers=AUTH)
    assert response.status_code == 200
    fixture = captured(response)
    del fixture["headers"]["last-modified-version"]

    with pytest.raises(CompatibilityError, match="Last-Modified-Version not provided"):
        zotero_client.call("sync_versions", ["user", 1, "item", {}], fixtures=fixture)


async def test_an_unchanged_library_is_accepted_without_a_body(
    library: Library, client: httpx.AsyncClient, zotero_client: ZoteroClient
) -> None:
    response = await client.get(
        "/users/1/items?format=versions", headers=AUTH | {"If-Modified-Since-Version": "7"}
    )
    assert response.status_code == 304

    result = zotero_client.call(
        "sync_versions", ["user", 1, "item", {}], fixtures=captured(response)
    )

    assert result["value"] is False
