"""The ``relations`` map on items and collections.

Upstream stores relations as predicate-object pairs and renders them with
``Zotero_DataObject::getRelations``: the first object for a predicate is emitted
as a string, and a second one turns the value into an array. Zotero uses that
for related items -- ``dc:relation`` with an array is an item related to several
others -- so collapsing it loses relationships the user made.

Two faults met here. Item relations were stored correctly and then read back
through a dict comprehension keyed on the predicate, which kept only the last
object. Collection relations were accepted and dropped: the write path never
looked at them and the serializer returned ``{}`` unconditionally.
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

OTHER = "http://zotero.org/users/1/items/AAAA2345"
ANOTHER = "http://zotero.org/users/1/items/BBBB2345"
A_COLLECTION = "http://zotero.org/users/1/collections/CCCC2345"


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


async def post(
    client: httpx.AsyncClient, path: str, payload: list[dict[str, Any]]
) -> dict[str, Any]:
    response = await client.post(path, headers=JSON, json=payload)
    body: dict[str, Any] = response.json()
    assert body["failed"] == {}, body["failed"]
    data: dict[str, Any] = body["successful"]["0"]["data"]
    return data


class TestItemRelations:
    async def test_one_object_is_a_string(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(
            client,
            "/users/1/items",
            [{"itemType": "book", "title": "Dune", "relations": {"dc:relation": OTHER}}],
        )

        assert stored["relations"] == {"dc:relation": OTHER}

    async def test_several_objects_stay_several(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # An item related to two others. Keyed on the predicate alone, the
        # second relation overwrites the first and the user loses one.
        stored = await post(
            client,
            "/users/1/items",
            [
                {
                    "itemType": "book",
                    "title": "Dune",
                    "relations": {"dc:relation": [OTHER, ANOTHER]},
                }
            ],
        )

        assert sorted(stored["relations"]["dc:relation"]) == sorted([OTHER, ANOTHER])

    async def test_they_survive_a_fetch(self, client: httpx.AsyncClient, library: Library) -> None:
        stored = await post(
            client,
            "/users/1/items",
            [
                {
                    "itemType": "book",
                    "title": "Dune",
                    "relations": {"dc:relation": [OTHER, ANOTHER]},
                }
            ],
        )

        fetched = await client.get(f"/users/1/items/{stored['key']}", headers=AUTH)

        assert sorted(fetched.json()["data"]["relations"]["dc:relation"]) == sorted(
            [OTHER, ANOTHER]
        )

    async def test_two_predicates_stay_apart(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(
            client,
            "/users/1/items",
            [
                {
                    "itemType": "book",
                    "title": "Dune",
                    "relations": {"dc:relation": OTHER, "owl:sameAs": ANOTHER},
                }
            ],
        )

        assert stored["relations"] == {"dc:relation": OTHER, "owl:sameAs": ANOTHER}

    async def test_an_empty_array_is_accepted_as_no_relations(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # Upstream allows it explicitly, "because it's annoying for some
        # clients otherwise". Rejecting it would fail the whole item.
        stored = await post(
            client, "/users/1/items", [{"itemType": "book", "title": "Dune", "relations": []}]
        )

        assert stored["relations"] == {}


class TestCollectionRelations:
    async def test_they_are_stored_rather_than_dropped(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(
            client,
            "/users/1/collections",
            [{"name": "Fiction", "relations": {"owl:sameAs": A_COLLECTION}}],
        )

        assert stored["relations"] == {"owl:sameAs": A_COLLECTION}

    async def test_they_survive_a_fetch(self, client: httpx.AsyncClient, library: Library) -> None:
        stored = await post(
            client,
            "/users/1/collections",
            [{"name": "Fiction", "relations": {"owl:sameAs": A_COLLECTION}}],
        )

        fetched = await client.get(f"/users/1/collections/{stored['key']}", headers=AUTH)

        assert fetched.json()["data"]["relations"] == {"owl:sameAs": A_COLLECTION}

    async def test_several_objects_stay_several(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(
            client,
            "/users/1/collections",
            [{"name": "Fiction", "relations": {"owl:sameAs": [A_COLLECTION, OTHER]}}],
        )

        assert sorted(stored["relations"]["owl:sameAs"]) == sorted([A_COLLECTION, OTHER])

    async def test_a_collection_without_relations_reports_an_empty_map(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(client, "/users/1/collections", [{"name": "Fiction"}])

        assert stored["relations"] == {}

    async def test_a_replacing_write_clears_them(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(
            client,
            "/users/1/collections",
            [{"name": "Fiction", "relations": {"owl:sameAs": A_COLLECTION}}],
        )
        del stored["relations"]

        again = await post(client, "/users/1/collections", [stored])

        assert again["relations"] == {}

    async def test_changing_them_is_not_an_unchanged_write(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(client, "/users/1/collections", [{"name": "Fiction"}])

        response = await client.post(
            "/users/1/collections",
            headers=JSON,
            json=[{**stored, "relations": {"owl:sameAs": A_COLLECTION}}],
        )

        assert response.json()["unchanged"] == {}
        assert set(response.json()["successful"]) == {"0"}

    async def test_resending_them_verbatim_is_unchanged(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        stored = await post(
            client,
            "/users/1/collections",
            [{"name": "Fiction", "relations": {"owl:sameAs": A_COLLECTION}}],
        )

        response = await client.post("/users/1/collections", headers=JSON, json=[stored])

        assert response.json()["unchanged"] == {"0": stored["key"]}

    async def test_a_non_object_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/collections",
            headers=JSON,
            json=[{"name": "Fiction", "relations": "nonsense"}],
        )

        assert response.json()["failed"]["0"]["code"] == 400
