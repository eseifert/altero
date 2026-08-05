"""Recording what happened in a group library, for notifying members later.

Activity is recorded once per write request rather than once per object, for
the same reason the library version moves once per request: a client syncing a
library uploads in batches, and fifty items arriving together is one thing that
happened, not fifty.

Recipients are deliberately *not* resolved here. A group with fifty members
would mean fifty rows written on the sync path, which is the hottest path there
is; the fan-out belongs to the sweep that sends, where it costs nobody's
request. See :mod:`altero.services.groupactivity`.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ActivityKind, GroupActivity, Library, LibraryType
from altero.services import groupactivity
from altero.services.auth import get_library
from tests.factories import make_api_key, make_group, make_user


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_user(session, user_id=2, username="member")
    return await make_group(session, group_id=100, owner_id=1, members={2: "member"})


async def recorded(session: AsyncSession) -> list[GroupActivity]:
    result = await session.scalars(select(GroupActivity).order_by(GroupActivity.id))
    return list(result)


class TestRecording:
    async def test_a_write_to_a_group_is_recorded(
        self, session: AsyncSession, group: Library
    ) -> None:
        await groupactivity.record(
            session, group, actor_id=1, kind=ActivityKind.ITEMS_CHANGED, count=3
        )
        await session.commit()

        rows = await recorded(session)
        assert len(rows) == 1
        assert rows[0].library_id == group.id
        assert rows[0].actor_id == 1
        assert rows[0].kind == ActivityKind.ITEMS_CHANGED
        assert rows[0].count == 3

    async def test_a_personal_library_records_nothing(
        self, session: AsyncSession, group: Library
    ) -> None:
        # Nobody else can see a personal library, so there is no one to tell.
        personal = await get_library(session, LibraryType.USER, 1)

        await groupactivity.record(
            session, personal, actor_id=1, kind=ActivityKind.ITEMS_CHANGED, count=3
        )
        await session.commit()

        assert await recorded(session) == []

    async def test_a_write_that_touched_nothing_records_nothing(
        self, session: AsyncSession, group: Library
    ) -> None:
        # A batch in which every object was unchanged moves no version and is
        # not something that happened.
        await groupactivity.record(
            session, group, actor_id=1, kind=ActivityKind.ITEMS_CHANGED, count=0
        )
        await session.commit()

        assert await recorded(session) == []

    async def test_each_kind_is_recorded_separately(
        self, session: AsyncSession, group: Library
    ) -> None:
        # A member subscribes per kind, so the kinds cannot be added together.
        await groupactivity.record(
            session, group, actor_id=1, kind=ActivityKind.ITEMS_CHANGED, count=2
        )
        await groupactivity.record(
            session, group, actor_id=1, kind=ActivityKind.ITEMS_DELETED, count=1
        )
        await session.commit()

        rows = await recorded(session)
        assert [(row.kind, row.count) for row in rows] == [
            (ActivityKind.ITEMS_CHANGED, 2),
            (ActivityKind.ITEMS_DELETED, 1),
        ]

    async def test_activity_starts_unflushed(self, session: AsyncSession, group: Library) -> None:
        # The sweep claims rows by stamping this, so a fresh row must be
        # visible to it.
        await groupactivity.record(
            session, group, actor_id=1, kind=ActivityKind.ITEMS_CHANGED, count=1
        )
        await session.commit()

        assert (await recorded(session))[0].flushed is None

    async def test_an_anonymous_write_is_recorded_without_an_actor(
        self, session: AsyncSession, group: Library
    ) -> None:
        # A write can reach a group library without a key that names a person.
        # It still happened, and everybody should hear about it.
        await groupactivity.record(
            session, group, actor_id=None, kind=ActivityKind.ITEMS_CHANGED, count=1
        )
        await session.commit()

        assert (await recorded(session))[0].actor_id is None


KEY = "AliceKeyAliceKeyAliceKey"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}


class TestOnTheWritePath:
    """What a real request records, which is what the sweep will send."""

    @pytest.fixture
    async def library(self, session: AsyncSession) -> Library:
        await make_user(session, user_id=1, username="alice", display_name="Alice")
        await make_api_key(session, key=KEY, user_id=1, all_groups_read=True, all_groups_write=True)
        return await make_group(session, group_id=100, owner_id=1)

    async def test_creating_items_records_one_event_for_the_batch(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        response = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[
                {"itemType": "book", "title": "One"},
                {"itemType": "book", "title": "Two"},
            ],
        )
        assert response.status_code == 200

        rows = await recorded(session)
        assert [(row.kind, row.count, row.actor_id) for row in rows] == [
            (ActivityKind.ITEMS_CHANGED, 2, 1)
        ]

    async def test_a_write_to_a_personal_library_records_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/items", headers=JSON, json=[{"itemType": "book", "title": "One"}]
        )
        assert response.status_code == 200

        assert await recorded(session) == []

    async def test_a_batch_that_wholly_failed_records_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Nothing was written and the library version did not move, so nothing
        # happened for anybody to hear about.
        response = await client.post(
            "/groups/100/items", headers=JSON, json=[{"itemType": "notAnItemType"}]
        )
        assert response.status_code == 200
        assert response.json()["failed"]

        assert await recorded(session) == []

    async def test_trashing_an_item_is_recorded_as_a_deletion(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Trashing is a field change on the wire, but it is what a person means
        # by deleting, and it is the event a member asked to be warned about.
        created = await client.post(
            "/groups/100/items", headers=JSON, json=[{"itemType": "book", "title": "One"}]
        )
        item = created.json()["successful"]["0"]["data"]

        response = await client.post(
            "/groups/100/items",
            headers=JSON,
            json=[{**item, "deleted": 1}],
        )
        assert response.status_code == 200

        rows = await recorded(session)
        assert [(row.kind, row.count) for row in rows] == [
            (ActivityKind.ITEMS_CHANGED, 1),
            (ActivityKind.ITEMS_DELETED, 1),
        ]

    async def test_deleting_items_outright_is_recorded_as_a_deletion(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        created = await client.post(
            "/groups/100/items", headers=JSON, json=[{"itemType": "book", "title": "One"}]
        )
        key = created.json()["successful"]["0"]["key"]
        version = created.headers["Last-Modified-Version"]

        response = await client.delete(
            f"/groups/100/items/{key}",
            headers=AUTH | {"If-Unmodified-Since-Version": version},
        )
        assert response.status_code == 204

        rows = await recorded(session)
        assert [(row.kind, row.count) for row in rows] == [
            (ActivityKind.ITEMS_CHANGED, 1),
            (ActivityKind.ITEMS_DELETED, 1),
        ]

    async def test_collections_are_recorded_under_their_own_kind(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        response = await client.post(
            "/groups/100/collections", headers=JSON, json=[{"name": "Reading"}]
        )
        assert response.status_code == 200

        rows = await recorded(session)
        assert [(row.kind, row.count) for row in rows] == [(ActivityKind.COLLECTIONS_CHANGED, 1)]
