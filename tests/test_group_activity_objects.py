"""Which objects a change touched, not just how many.

dataserver#89 asks for "what was modified", and the counts alone do not answer
it. Each activity row now carries the objects behind it, as key and name.

The name is a **snapshot**, taken when the change happened. That follows the
rule `services/notifications.py` already states: a record of something says
what was true when it was raised, so an item renamed afterwards does not
silently rewrite history and one deleted afterwards does not become a blank
row. It is also the only way a deletion can be shown at all -- there is nothing
left to look the name up from.

Volume is bounded by the API itself: a write request carries at most
`writes.MAX_OBJECTS` objects, so one activity row can never hold more than
fifty of these however large the library is.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ActivityKind, GroupActivity, GroupActivityObject, Library
from tests.factories import make_api_key, make_group, make_user

KEY = "AliceKeyAliceKeyAliceKey"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    await make_user(session, user_id=1, username="alice", display_name="Alice")
    await make_api_key(session, key=KEY, user_id=1, all_groups_read=True, all_groups_write=True)
    return await make_group(session, group_id=100, owner_id=1)


async def rows(session: AsyncSession) -> list[GroupActivity]:
    result = await session.scalars(select(GroupActivity).order_by(GroupActivity.id))
    return list(result)


async def objects_of(session: AsyncSession, activity: GroupActivity) -> list[tuple[str, str]]:
    result = await session.scalars(
        select(GroupActivityObject)
        .where(GroupActivityObject.activity_id == activity.id)
        .order_by(GroupActivityObject.id)
    )
    return [(row.object_key, row.name) for row in result]


class TestRecordingWhat:
    async def test_created_items_are_named(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[
                {"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"},
                {"itemType": "book", "key": "BBBB2345", "title": "Omoo"},
            ],
        )

        (activity,) = await rows(session)
        assert await objects_of(session, activity) == [
            ("AAAA2345", "Moby-Dick"),
            ("BBBB2345", "Omoo"),
        ]

    async def test_a_note_is_named_by_its_opening(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        # A note has no title, and the item list shows the start of its text.
        # The same derivation is reused rather than a second one written.
        await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{"itemType": "note", "key": "NNNN2345", "note": "<p>Call me Ishmael.</p>"}],
        )

        (activity,) = await rows(session)
        assert await objects_of(session, activity) == [("NNNN2345", "Call me Ishmael.")]

    async def test_collections_are_named(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await client.post(
            "/groups/100/collections",
            headers=JSON,
            json=[{"key": "CCCC2345", "name": "Whaling"}],
        )

        (activity,) = await rows(session)
        assert await objects_of(session, activity) == [("CCCC2345", "Whaling")]

    async def test_a_change_records_the_name_it_had_afterwards(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        created = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"}],
        )
        item = created.json()["successful"]["0"]["data"]

        await client.post(
            "/groups/100/items", headers=JSON, json=[{**item, "title": "Moby-Dick; or, The Whale"}]
        )

        first, second = await rows(session)
        assert await objects_of(session, first) == [("AAAA2345", "Moby-Dick")]
        assert await objects_of(session, second) == [("AAAA2345", "Moby-Dick; or, The Whale")]

    async def test_renaming_later_does_not_rewrite_the_earlier_entry(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        # The whole reason the name is stored rather than joined: a log that
        # changed retroactively would not be a log.
        created = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"}],
        )
        item = created.json()["successful"]["0"]["data"]
        await client.post("/groups/100/items", headers=JSON, json=[{**item, "title": "Renamed"}])

        first, _ = await rows(session)
        assert await objects_of(session, first) == [("AAAA2345", "Moby-Dick")]


class TestDeletions:
    async def test_a_trashed_item_is_named(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        created = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"}],
        )
        item = created.json()["successful"]["0"]["data"]

        await client.post("/groups/100/items", headers=JSON, json=[{**item, "deleted": 1}])

        _, trashing = await rows(session)
        assert trashing.kind == ActivityKind.ITEMS_DELETED
        assert await objects_of(session, trashing) == [("AAAA2345", "Moby-Dick")]

    async def test_an_item_deleted_outright_is_named(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        # Nothing is left to look the name up from afterwards, so it has to be
        # taken before the row goes.
        created = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"}],
        )
        version = created.headers["Last-Modified-Version"]

        response = await client.delete(
            "/groups/100/items/AAAA2345",
            headers=AUTH | {"If-Unmodified-Since-Version": version},
        )
        assert response.status_code == 204

        _, deletion = await rows(session)
        assert deletion.kind == ActivityKind.ITEMS_DELETED
        assert await objects_of(session, deletion) == [("AAAA2345", "Moby-Dick")]

    async def test_several_deleted_at_once_are_all_named(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        created = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[
                {"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"},
                {"itemType": "book", "key": "BBBB2345", "title": "Omoo"},
            ],
        )
        version = created.headers["Last-Modified-Version"]

        await client.delete(
            "/groups/100/items?itemKey=AAAA2345,BBBB2345",
            headers=AUTH | {"If-Unmodified-Since-Version": version},
        )

        _, deletion = await rows(session)
        assert sorted(await objects_of(session, deletion)) == [
            ("AAAA2345", "Moby-Dick"),
            ("BBBB2345", "Omoo"),
        ]

    async def test_a_change_and_a_trashing_in_one_batch_are_kept_apart(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        created = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[
                {"itemType": "book", "key": "AAAA2345", "title": "Moby-Dick"},
                {"itemType": "book", "key": "BBBB2345", "title": "Omoo"},
            ],
        )
        first, second = (created.json()["successful"][index]["data"] for index in ("0", "1"))

        await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{**first, "title": "Changed"}, {**second, "deleted": 1}],
        )

        _, changed, trashed = await rows(session)
        assert await objects_of(session, changed) == [("AAAA2345", "Changed")]
        assert await objects_of(session, trashed) == [("BBBB2345", "Omoo")]


class TestHousekeeping:
    async def test_the_count_still_matches_the_objects(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{"itemType": "book", "title": f"Book {index}"} for index in range(3)],
        )

        (activity,) = await rows(session)
        assert activity.count == 3
        assert len(await objects_of(session, activity)) == 3

    async def test_a_personal_library_records_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await client.post(
            "/users/1/items", headers=JSON, json=[{"itemType": "book", "title": "Moby-Dick"}]
        )

        assert await rows(session) == []
        assert list(await session.scalars(select(GroupActivityObject))) == []

    async def test_deleting_the_group_takes_them_with_it(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        from altero.services import groups as groups_service

        await client.post(
            "/groups/100/items", headers=JSON, json=[{"itemType": "book", "title": "Moby-Dick"}]
        )

        await groups_service.delete_group(session, group)
        await session.commit()

        assert list(await session.scalars(select(GroupActivityObject))) == []
