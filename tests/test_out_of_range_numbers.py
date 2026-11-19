"""Numbers beyond what the database compares with.

SQLite refuses a bound integer past 64 bits, and PostgreSQL one past the 32 bits
of its version columns, so ``since=9223372036854775808`` failed with a 500.
Upstream accepts any number there and answers with nothing newer; ``start``
past the end is an empty page.
"""

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import (
    index_fulltext,
    make_api_key,
    make_collection,
    make_item,
    make_user,
    tag_item,
)

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
HUGE = str(2**63)


@pytest.fixture
async def library(session: AsyncSession, client: httpx2.AsyncClient) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    item = await make_item(session, library, key="BOOK2345", version=5)
    await make_collection(session, library, key="CCCC2345", version=5)
    await make_collection(session, library, key="GONE2345", version=5)
    await tag_item(session, library, item, "whales")
    await index_fulltext(session, library, item, "Call me Ishmael.")
    await client.put("/users/1/settings/tagColors", headers=AUTH, json={"value": []})
    await client.delete(
        "/users/1/collections/GONE2345", headers=AUTH | {"If-Unmodified-Since-Version": "11"}
    )
    return library


@pytest.mark.parametrize(
    "path",
    [
        "/users/1/items",
        "/users/1/items?format=versions",
        "/users/1/collections",
        "/users/1/tags",
        "/users/1/deleted",
        "/users/1/fulltext",
        "/users/1/settings",
    ],
)
async def test_a_since_beyond_any_version_finds_nothing_newer(
    client: httpx2.AsyncClient, library: Library, path: str
) -> None:
    separator = "&" if "?" in path else "?"

    response = await client.get(f"{path}{separator}since={HUGE}", headers=AUTH)
    everything = await client.get(f"{path}{separator}since=-{HUGE}", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json() in ([], {}) or all(not value for value in response.json().values())
    assert everything.status_code == 200, everything.text
    assert everything.json()


async def test_a_start_beyond_the_end_is_an_empty_page(
    client: httpx2.AsyncClient, library: Library
) -> None:
    response = await client.get(f"/users/1/items?start={HUGE}", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == []
    assert response.headers["Total-Results"] == "1"


async def test_settings_refuse_a_since_that_is_not_a_number(
    client: httpx2.AsyncClient, library: Library
) -> None:
    """Upstream checks it is numeric; here it failed with a 500."""
    response = await client.get("/users/1/settings?since=abc", headers=AUTH)

    assert response.status_code == 400
    assert response.text == "Invalid 'since' value 'abc'"
