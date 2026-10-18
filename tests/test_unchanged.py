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

from typing import Any, ClassVar

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


class TestTheComparisonAgreesWithWriting:
    """Whether an item is unchanged is decided before anything is written.

    The answer must be the one writing it and comparing would give, so every
    payload shape here is put both ways: applied inside a savepoint and the
    rows read back (the oracle), and through ``save_item(detect_unchanged=True)``
    -- and the two must agree, as well as match what each case expects.
    """

    @pytest.fixture
    async def stored(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> dict[str, dict[str, Any]]:
        collections = await send(client, "/users/1/collections", [{"name": "One"}, {"name": "Two"}])
        keys = [entry["key"] for entry in collections.json()["successful"].values()]
        parent = {
            "itemType": "book",
            "title": "Dune",
            "date": "1965",
            "creators": [
                {"creatorType": "author", "firstName": "Frank", "lastName": "Herbert"},
                {"creatorType": "editor", "name": "Chilton Books"},
            ],
            "tags": [{"tag": "fiction"}, {"tag": "auto", "type": 1}],
            "collections": keys,
            "relations": {"dc:relation": "http://zotero.org/users/1/items/AAAA2345"},
            # In the past, so that "now" -- what a write without one stamps --
            # cannot happen to equal it.
            "dateModified": "2020-01-01T00:00:00Z",
        }
        created = (await send(client, "/users/1/items", [parent])).json()["successful"]["0"]
        note = {
            "itemType": "note",
            "note": "<p>Spice</p>",
            "parentItem": created["key"],
            "dateModified": "2020-01-01T00:00:00Z",
        }
        child = (await send(client, "/users/1/items", [note])).json()["successful"]["0"]
        other = await send(client, "/users/1/items", [{"itemType": "book", "title": "Other"}])
        return {
            "parent": created["data"],
            "child": child["data"],
            "other": other.json()["successful"]["0"]["data"],
        }

    CASES: ClassVar[list[tuple[str, str, Any, bool]]] = [
        # (name, which item, how to change what was stored, expected unchanged)
        ("verbatim", "parent", lambda d, o: d, True),
        ("verbatim child", "child", lambda d, o: d, True),
        ("no dateModified", "parent", lambda d, o: _without(d, "dateModified"), False),
        ("title", "parent", lambda d, o: {**d, "title": "Dune Messiah"}, False),
        ("only key and dates", "parent", lambda d, o: _only(d, "dateModified"), True),
        ("tags reordered", "parent", lambda d, o: {**d, "tags": d["tags"][::-1]}, True),
        ("tag twice", "parent", lambda d, o: {**d, "tags": d["tags"] + d["tags"][:1]}, True),
        ("tags emptied", "parent", lambda d, o: {**d, "tags": []}, False),
        ("tags left out", "parent", lambda d, o: _without(d, "tags"), True),
        ("tag type", "parent", lambda d, o: {**d, "tags": [{"tag": "fiction", "type": 1}]}, False),
        (
            "creators reordered",
            "parent",
            lambda d, o: {**d, "creators": d["creators"][::-1]},
            False,
        ),
        ("creators left out", "parent", lambda d, o: _without(d, "creators"), True),
        ("creators emptied", "parent", lambda d, o: {**d, "creators": []}, False),
        (
            "collections reordered",
            "parent",
            lambda d, o: {**d, "collections": d["collections"][::-1]},
            True,
        ),
        (
            "collection twice",
            "parent",
            lambda d, o: {**d, "collections": d["collections"] * 2},
            True,
        ),
        ("collections emptied", "parent", lambda d, o: {**d, "collections": []}, False),
        ("relations emptied", "parent", lambda d, o: {**d, "relations": {}}, False),
        ("relations left out", "parent", lambda d, o: _without(d, "relations"), True),
        ("trashed", "parent", lambda d, o: {**d, "deleted": True}, False),
        ("not trashed, said so", "parent", lambda d, o: {**d, "deleted": False}, True),
        ("not published, said so", "parent", lambda d, o: {**d, "inPublications": False}, True),
        ("empty field added", "parent", lambda d, o: {**d, "volume": ""}, False),
        ("null field added", "parent", lambda d, o: {**d, "volume": None}, False),
        ("field emptied", "parent", lambda d, o: {**d, "date": ""}, False),
        (
            "item type",
            "parent",
            lambda d, o: {**d, "itemType": "bookSection"},
            False,
        ),
        ("dateAdded", "parent", lambda d, o: {**d, "dateAdded": "2001-01-01T00:00:00Z"}, False),
        ("note text", "child", lambda d, o: {**d, "note": "<p>Melange</p>"}, False),
        ("note left out", "child", lambda d, o: _without(d, "note"), True),
        ("same parent", "child", lambda d, o: d, True),
        ("other parent", "child", lambda d, o: {**d, "parentItem": o["key"]}, False),
        ("parent left out", "child", lambda d, o: _without(d, "parentItem"), True),
    ]

    @pytest.mark.parametrize(
        ("name", "which", "change", "expected"), CASES, ids=[c[0] for c in CASES]
    )
    async def test_the_two_agree(
        self,
        session: AsyncSession,
        library: Library,
        stored: dict[str, dict[str, Any]],
        name: str,
        which: str,
        change: Any,
        expected: bool,
    ) -> None:
        from altero.services.itemwrites import save_item

        payload = change(dict(stored[which]), stored["other"])
        item_id = (await _rows(session, stored[which]["key"]))["id"]

        before = await _observed(session, item_id)
        savepoint = await session.begin_nested()
        await save_item(session, library, dict(payload), 99, replace=False)
        await session.flush()
        written = await _observed(session, item_id)
        await savepoint.rollback()
        session.expunge_all()

        savepoint = await session.begin_nested()
        answer = await save_item(
            session, library, dict(payload), 99, replace=False, detect_unchanged=True
        )
        await savepoint.rollback()
        session.expunge_all()

        assert (before == written) == expected, "the oracle disagrees with the case"
        assert (answer is None) == expected


def _without(data: dict[str, Any], name: str) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != name}


def _only(data: dict[str, Any], *names: str) -> dict[str, Any]:
    return {key: data[key] for key in ("key", "version", *names)}


async def _rows(session: AsyncSession, key: str) -> dict[str, Any]:
    from sqlalchemy import select

    from altero.models import Item

    row = (await session.execute(select(Item.__table__).where(Item.key == key))).mappings().one()
    return dict(row)


async def _observed(session: AsyncSession, item_id: int) -> tuple[Any, ...]:
    """What is stored for an item, read from its rows rather than its ORM object."""
    from sqlalchemy import select

    from altero.models import (
        Collection,
        CollectionItem,
        Item,
        ItemCreator,
        ItemField,
        ItemRelation,
        ItemTag,
        Tag,
    )

    item = (
        (await session.execute(select(Item.__table__).where(Item.id == item_id))).mappings().one()
    )
    scalars = tuple(
        item[name]
        for name in (
            "item_type",
            "deleted",
            "in_publications",
            "date_added",
            "date_modified",
            "parent_id",
        )
    )

    async def rows(statement: Any) -> tuple[Any, ...]:
        return tuple(sorted(tuple(row) for row in (await session.execute(statement)).all()))

    return (
        scalars,
        await rows(select(ItemField.field, ItemField.value).where(ItemField.item_id == item_id)),
        await rows(
            select(
                ItemCreator.position,
                ItemCreator.creator_type,
                ItemCreator.first_name,
                ItemCreator.last_name,
                ItemCreator.name,
            ).where(ItemCreator.item_id == item_id)
        ),
        await rows(
            select(ItemRelation.predicate, ItemRelation.object).where(
                ItemRelation.item_id == item_id
            )
        ),
        await rows(
            select(Tag.name, Tag.type)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item_id)
        ),
        await rows(
            select(Collection.key)
            .join(CollectionItem, CollectionItem.collection_id == Collection.id)
            .where(CollectionItem.item_id == item_id)
        ),
    )
