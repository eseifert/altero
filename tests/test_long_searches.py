"""Searches longer than SQLite builds a statement for.

SQLite refuses a ``LIKE`` or ``GLOB`` pattern over 50,000 bytes and a statement
nested a thousand deep, so a long ``q`` -- or one of a thousand words -- failed
with a 500. PostgreSQL and upstream's MySQL answer both.
"""

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user, tag_item

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
NEEDLE = "Ä" + "walfisch" * 7500


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    note = await make_item(
        session, library, key="NOTE2345", item_type="note", fields={"note": f"x {NEEDLE} y"}
    )
    await tag_item(session, library, note, "whale")
    await make_item(session, library, key="BOOK2345", fields={"title": "Moby-Dick"})
    return library


@pytest.mark.parametrize("qmode", ["titleCreatorYear", "everything"])
async def test_a_search_longer_than_a_sqlite_pattern_is_answered(
    client: httpx2.AsyncClient, library: Library, qmode: str
) -> None:
    assert len(NEEDLE.encode()) > 50_000

    response = await client.get(
        "/users/1/items", params={"q": NEEDLE.lower(), "qmode": qmode}, headers=AUTH
    )

    assert response.status_code == 200, response.text
    found = [entry["key"] for entry in response.json()]
    assert found == (["NOTE2345"] if qmode == "everything" else [])


@pytest.mark.parametrize("qmode", ["contains", "startsWith"])
async def test_a_tag_search_longer_than_a_sqlite_pattern_is_answered(
    client: httpx2.AsyncClient, library: Library, qmode: str
) -> None:
    response = await client.get("/users/1/tags", params={"q": NEEDLE, "qmode": qmode}, headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_a_long_pattern_with_wildcards_inside_is_refused(
    client: httpx2.AsyncClient, library: Library
) -> None:
    """Without ``LIKE``, a wildcard inside cannot mean what it means there.

    SQLite alone: PostgreSQL takes the pattern as it is.
    """
    response = await client.get(
        "/users/1/items", params={"q": f"{'a' * 26_000}%{'a' * 26_000}"}, headers=AUTH
    )

    assert response.status_code == 400
    assert response.text == "The search is too long"


async def test_a_search_of_a_thousand_words_is_answered(
    client: httpx2.AsyncClient, library: Library
) -> None:
    words = " ".join(["moby", *(f"dick{index}" for index in range(1200))])

    found = await client.get("/users/1/items", params={"q": "moby dick moby"}, headers=AUTH)
    response = await client.get(
        "/users/1/items", params={"q": words, "qmode": "everything"}, headers=AUTH
    )

    assert [entry["key"] for entry in found.json()] == ["BOOK2345"]
    assert response.status_code == 200, response.text
    assert response.json() == []
