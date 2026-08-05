"""Reading back what happened in a group library.

dataserver#89 has been open since 2019, opened by Zotero's own maintainer off a
forum thread asking for exactly this. The workaround offered there is a group
RSS feed that "won't show what was modified, and won't show deletions".

The rows are already being written -- the digest keeps them rather than
deleting them once it has sent. This is the reading half, so the same record
answers two questions: what to tell people, and what happened.

Deliberately not a per-object history. A row is one write request, which is one
library version, and it says who and how many. Recording which objects would
mean a row per object per change, and the thing people ask for is "has anything
happened here lately", which the counts answer.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


async def sign_up(client: httpx.AsyncClient, username: str = "ada") -> httpx.Response:
    return await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": "correct horse battery",
            "email": f"{username}@example.org",
        },
    )


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["altero_csrf"]}


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    assert (await sign_up(client)).status_code == 201
    return client


@pytest.fixture
async def group(ada: httpx.AsyncClient) -> int:
    response = await ada.post("/web/groups", json={"name": "Kollaps"}, headers=csrf(ada))
    assert response.status_code == 201
    return int(response.json()["id"])


async def record(
    session: AsyncSession,
    library_id: int,
    *,
    kind: str = "items_changed",
    count: int = 1,
    actor_id: int | None = 1,
) -> None:
    from altero.models import ActivityKind, Library
    from altero.services import groupactivity

    library = await session.get(Library, library_id)
    assert library is not None
    await groupactivity.record(
        session, library, actor_id=actor_id, kind=ActivityKind(kind), count=count
    )
    await session.commit()


class TestReading:
    async def test_an_untouched_group_has_an_empty_log(
        self, ada: httpx.AsyncClient, group: int
    ) -> None:
        response = await ada.get(f"/web/groups/{group}/activity")

        assert response.status_code == 200
        assert response.json() == {"activity": [], "total": 0}

    async def test_an_entry_names_what_happened_and_who(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        await record(session, group, kind="items_changed", count=4)

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        (entry,) = body["activity"]
        assert entry["kind"] == "items_changed"
        assert entry["count"] == 4
        assert entry["actor"]["username"] == "ada"
        assert entry["when"].endswith("Z")

    async def test_an_entry_names_the_objects_it_touched(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        # The point of dataserver#89: "what was modified", not merely how much.
        from altero.models import GroupActivity, GroupActivityObject

        await record(session, group, count=2)
        activity = (await session.scalars(select(GroupActivity))).one()
        session.add_all(
            [
                GroupActivityObject(
                    activity_id=activity.id, object_key="AAAA2345", name="Moby-Dick"
                ),
                GroupActivityObject(activity_id=activity.id, object_key="BBBB2345", name="Omoo"),
            ]
        )
        await session.commit()

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        assert body["activity"][0]["objects"] == [
            {"key": "AAAA2345", "name": "Moby-Dick"},
            {"key": "BBBB2345", "name": "Omoo"},
        ]

    async def test_an_entry_with_no_objects_recorded_carries_an_empty_list(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        # Everything written before this existed, which is what an upgraded
        # instance is full of. It has a count and no names, and the interface
        # has to cope rather than break.
        await record(session, group, count=3)

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        assert body["activity"][0]["objects"] == []
        assert body["activity"][0]["count"] == 3

    async def test_the_newest_comes_first(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        await record(session, group, kind="items_changed")
        await record(session, group, kind="items_deleted")

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        assert [entry["kind"] for entry in body["activity"]] == [
            "items_deleted",
            "items_changed",
        ]

    async def test_a_write_by_nobody_has_no_actor(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        # A key that names no person can still reach a group library.
        await record(session, group, actor_id=None)

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        assert body["activity"][0]["actor"] is None

    async def test_entries_are_shown_whether_or_not_they_have_been_sent(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        # The log is the record, not the outbox: an entry nobody subscribed to
        # is still something that happened.
        from datetime import UTC, datetime

        from sqlalchemy import update

        from altero.models import GroupActivity

        await record(session, group)
        await session.execute(
            update(GroupActivity).values(flushed=datetime.now(UTC).replace(tzinfo=None))
        )
        await session.commit()

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        assert len(body["activity"]) == 1


class TestPaging:
    async def test_the_page_is_capped_and_the_total_reported(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        for _ in range(5):
            await record(session, group)

        body = (await ada.get(f"/web/groups/{group}/activity?limit=2")).json()

        assert len(body["activity"]) == 2
        assert body["total"] == 5

    async def test_start_moves_through_the_log(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        for count in (1, 2, 3):
            await record(session, group, count=count)

        body = (await ada.get(f"/web/groups/{group}/activity?limit=1&start=1")).json()

        # Newest first, so start=1 is the middle one.
        assert [entry["count"] for entry in body["activity"]] == [2]

    async def test_an_unreadable_limit_is_ignored(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        await record(session, group)

        response = await ada.get(f"/web/groups/{group}/activity?limit=abc")

        assert response.status_code == 200
        assert len(response.json()["activity"]) == 1


class TestWhoMaySee:
    async def test_a_stranger_may_not(
        self, client: httpx.AsyncClient, ada: httpx.AsyncClient, group: int
    ) -> None:
        await ada.post("/web/auth/logout", headers=csrf(ada))

        response = await client.get(f"/web/groups/{group}/activity")

        assert response.status_code in (401, 403)

    async def test_a_non_member_may_not(
        self, client: httpx.AsyncClient, ada: httpx.AsyncClient, group: int
    ) -> None:
        # Not found rather than forbidden, as everywhere else in /web: a
        # stranger learns nothing about which private groups exist.
        await ada.post("/web/auth/logout", headers=csrf(ada))
        assert (await sign_up(client, "grace")).status_code in (201, 403)

        response = await client.get(f"/web/groups/{group}/activity")

        assert response.status_code in (401, 403, 404)

    async def test_an_api_key_may_not(
        self, client: httpx.AsyncClient, ada: httpx.AsyncClient, group: int, session: AsyncSession
    ) -> None:
        # The v3 API is API-key only and /web is cookie only; the log is /web.
        #
        # The sign-out matters: `ada` is the same client object, so without it
        # the session cookie answers the request and the key is never consulted
        # -- the test would pass while testing nothing.
        from tests.factories import make_api_key

        await make_api_key(session, key="KeyKeyKeyKeyKeyKeyKeyKey", user_id=1, all_groups_read=True)
        await ada.post("/web/auth/logout", headers=csrf(ada))

        response = await client.get(
            f"/web/groups/{group}/activity",
            headers={"Zotero-API-Key": "KeyKeyKeyKeyKeyKeyKeyKey"},
        )

        assert response.status_code in (401, 403)

    async def test_a_plain_member_may(
        self, ada: httpx.AsyncClient, session: AsyncSession, group: int
    ) -> None:
        # Everybody in a group can see what happened in it. Restricting the log
        # to administrators would make it a supervision tool rather than a way
        # of keeping up, which is what it was asked for.
        from altero.models import GroupMember, User

        session.add(User(id=2, username="grace", display_name="Grace"))
        await session.flush()
        session.add(GroupMember(library_id=group, user_id=2, role="member"))
        await session.commit()
        await record(session, group, actor_id=2)

        body = (await ada.get(f"/web/groups/{group}/activity")).json()

        assert body["activity"][0]["actor"]["username"] == "grace"
