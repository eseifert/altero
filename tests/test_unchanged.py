"""Recognising an object that was sent again without changing.

Upstream compares an incoming object with the stored one and, when nothing
differs, reports it under ``unchanged`` and leaves its version alone
(``Zotero_DataObjects::updateMultipleFromJSON`` calls ``addUnchanged`` when
``updateFromJSON`` reports no change). altero used to write it again and stamp a
new version, so a client re-sending what it already held made every other client
re-download it.

The realistic case is the one these tests use: take what the server returned and
send it straight back, which is what a client does out of its sync cache.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
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


async def send(
    client: httpx.AsyncClient, path: str, payload: list[dict[str, Any]]
) -> httpx.Response:
    return await client.post(path, headers=JSON, json=payload)


class TestItems:
    async def test_an_item_sent_back_verbatim_is_unchanged(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/items", [stored])

        assert again.json()["successful"] == {}
        assert again.json()["unchanged"] == {"0": stored["key"]}

    async def test_an_unchanged_item_keeps_its_version(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        await send(client, "/users/1/items", [stored])

        fetched = await client.get(f"/users/1/items/{stored['key']}", headers=AUTH)
        assert fetched.json()["version"] == stored["version"]

    async def test_the_library_version_does_not_move(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # The whole point: a re-sent object that advanced the library would make
        # every other client re-download something that never changed.
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]
        settled = created.headers["Last-Modified-Version"]

        again = await send(client, "/users/1/items", [stored])

        assert again.headers["Last-Modified-Version"] == settled

    async def test_a_changed_title_is_still_written(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/items", [{**stored, "title": "Dune Messiah"}])

        assert again.json()["unchanged"] == {}
        assert again.json()["successful"]["0"]["data"]["title"] == "Dune Messiah"
        assert again.headers["Last-Modified-Version"] == "12"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("tags", [{"tag": "fiction"}]),
            ("creators", [{"creatorType": "author", "firstName": "F", "lastName": "H"}]),
            ("relations", {"dc:replaces": "http://zotero.org/users/1/items/AAAA2345"}),
            ("deleted", 1),
            ("dateModified", "2030-01-01T00:00:00Z"),
        ],
    )
    async def test_a_difference_anywhere_counts_as_changed(
        self, client: httpx.AsyncClient, library: Library, field: str, value: Any
    ) -> None:
        # Comparing only the obvious scalars would report an item unchanged
        # after its tags or its creators had been rewritten.
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/items", [{**stored, field: value}])

        assert again.json()["unchanged"] == {}
        assert set(again.json()["successful"]) == {"0"}

    async def test_a_collection_move_counts_as_changed(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        collection = await send(client, "/users/1/collections", [{"name": "Fiction"}])
        collection_key = collection.json()["successful"]["0"]["data"]["key"]
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/items", [{**stored, "collections": [collection_key]}])

        assert again.json()["unchanged"] == {}


class TestCollectionsAndSearches:
    async def test_a_collection_sent_back_verbatim_is_unchanged(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(client, "/users/1/collections", [{"name": "Fiction"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/collections", [stored])

        assert again.json()["unchanged"] == {"0": stored["key"]}
        assert again.headers["Last-Modified-Version"] == "11"

    async def test_a_renamed_collection_is_written(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(client, "/users/1/collections", [{"name": "Fiction"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/collections", [{**stored, "name": "Novels"}])

        assert again.json()["unchanged"] == {}
        assert again.headers["Last-Modified-Version"] == "12"

    async def test_a_reparented_collection_is_written(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        parent = await send(client, "/users/1/collections", [{"name": "Parent"}])
        parent_key = parent.json()["successful"]["0"]["data"]["key"]
        child = await send(client, "/users/1/collections", [{"name": "Child"}])
        stored = child.json()["successful"]["0"]["data"]

        again = await send(
            client, "/users/1/collections", [{**stored, "parentCollection": parent_key}]
        )

        assert again.json()["unchanged"] == {}

    async def test_a_search_sent_back_verbatim_is_unchanged(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(
            client,
            "/users/1/searches",
            [
                {
                    "name": "Recent",
                    "conditions": [{"condition": "title", "operator": "contains", "value": "Dune"}],
                }
            ],
        )
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/searches", [stored])

        assert again.json()["unchanged"] == {"0": stored["key"]}

    async def test_an_edited_condition_is_written(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(
            client,
            "/users/1/searches",
            [
                {
                    "name": "Recent",
                    "conditions": [{"condition": "title", "operator": "contains", "value": "Dune"}],
                }
            ],
        )
        stored = created.json()["successful"]["0"]["data"]
        edited = {
            **stored,
            "conditions": [{"condition": "title", "operator": "contains", "value": "Messiah"}],
        }

        again = await send(client, "/users/1/searches", [edited])

        assert again.json()["unchanged"] == {}


class TestMixedBatches:
    async def test_one_of_each_costs_exactly_one_version(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune"}, {"itemType": "book", "title": "Emma"}],
        )
        first = created.json()["successful"]["0"]["data"]
        second = created.json()["successful"]["1"]["data"]

        again = await send(client, "/users/1/items", [first, {**second, "title": "Persuasion"}])

        assert again.json()["unchanged"] == {"0": first["key"]}
        assert set(again.json()["successful"]) == {"1"}
        # One request, one version -- and the unchanged object does not take it.
        assert again.headers["Last-Modified-Version"] == "12"
        assert again.json()["successful"]["1"]["version"] == 12

    async def test_an_unchanged_object_beside_a_failure_is_still_unchanged(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        created = await send(client, "/users/1/items", [{"itemType": "book", "title": "Dune"}])
        stored = created.json()["successful"]["0"]["data"]

        again = await send(client, "/users/1/items", [stored, {"itemType": "nonsense"}])

        assert again.json()["unchanged"] == {"0": stored["key"]}
        assert set(again.json()["failed"]) == {"1"}
