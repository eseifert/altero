"""The browser's merge endpoint: a single, versioned transaction."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from altero.models import GroupActivity, Item, Library, User
from altero.services import groups, writes
from tests import factories
from tests.test_web_routes import csrf_headers, register


@dataclass
class MergeCase:
    library: Library
    master: Item
    other: Item
    note: Item

    @property
    def url(self) -> str:
        return f"/web/libraries/{self.library.id}/items/merge"

    def body(self, **extra: Any) -> dict[str, Any]:
        return {"master": self.master.key, "others": [self.other.key], "fields": {}, **extra}


async def seed(session: AsyncSession, library: Library) -> MergeCase:
    master = await factories.make_item(
        session, library, fields={"title": "Original", "extra": "Keep"}
    )
    other = await factories.make_item(session, library, fields={"title": "Duplicate"})
    note = await factories.make_item(
        session, library, item_type="note", parent=other, fields={"note": "<p>Working</p>"}
    )
    master.date_added = datetime(2020, 1, 1)
    other.date_added = datetime(1990, 1, 1)
    library.version = 10
    await session.commit()
    return MergeCase(library, master, other, note)


@pytest.fixture
async def case(client: httpx2.AsyncClient, session: AsyncSession) -> MergeCase:
    assert (await register(client)).status_code == 201
    library = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert library is not None
    return await seed(session, library)


def headers(client: httpx2.AsyncClient, version: str = "10") -> dict[str, str]:
    return csrf_headers(client) | {"If-Unmodified-Since-Version": version}


async def unchanged(client: httpx2.AsyncClient, case: MergeCase) -> None:
    master = (await client.get(f"/web/libraries/{case.library.id}/items/{case.master.key}")).json()
    other = (await client.get(f"/web/libraries/{case.library.id}/items/{case.other.key}")).json()
    assert master["data"]["title"] == "Original"
    assert not other["data"].get("deleted")
    libraries = (await client.get("/web/libraries")).json()
    assert next(row["version"] for row in libraries if row["id"] == case.library.id) == 10


async def test_chosen_values_and_children_arrive_in_one_version(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase
) -> None:
    key = await factories.make_api_key(session)
    response = await client.post(
        case.url,
        headers=headers(client),
        json=case.body(
            fields={
                "title": "Chosen",
                "creators": [{"creatorType": "author", "name": "A collective"}],
            }
        ),
    )
    assert response.status_code == 200
    assert response.headers["Last-Modified-Version"] == "11"
    changed = response.json()["items"]
    assert changed[0]["key"] == case.master.key
    assert {item["version"] for item in changed} == {11}
    by_key = {item["key"]: item["data"] for item in changed}
    assert set(by_key) == {case.master.key, case.other.key, case.note.key}
    assert by_key[case.master.key]["title"] == "Chosen"
    assert by_key[case.master.key]["extra"] == "Keep"
    assert by_key[case.master.key]["creators"] == [
        {"creatorType": "author", "name": "A collective"}
    ]
    assert by_key[case.master.key]["dateAdded"].startswith("1990-01-01")
    assert by_key[case.master.key]["relations"]["dc:replaces"].endswith("/" + case.other.key)
    assert by_key[case.other.key]["deleted"] == 1
    assert by_key[case.note.key]["parentItem"] == case.master.key
    synced = await client.get(
        "/users/1/items?since=10&includeTrashed=1&format=versions",
        headers={"Zotero-API-Key": key.key},
    )
    assert synced.json() == {key: 11 for key in by_key}


async def test_empty_field_choices_keep_master_content(
    client: httpx2.AsyncClient, case: MergeCase
) -> None:
    response = await client.post(case.url, headers=headers(client), json=case.body())
    assert response.status_code == 200
    assert response.json()["items"][0]["data"]["title"] == "Original"


@pytest.mark.parametrize(
    ("version", "status"), [(None, 428), ("9", 412), ("999", 412), ("no", 400)]
)
async def test_version_is_required_and_must_match_exactly(
    client: httpx2.AsyncClient, case: MergeCase, version: str | None, status: int
) -> None:
    request_headers = csrf_headers(client) if version is None else headers(client, version)
    response = await client.post(
        case.url, headers=request_headers, json=case.body(fields={"title": "Lost"})
    )
    assert response.status_code == status
    await unchanged(client, case)


async def test_no_cookie_and_an_api_key_are_not_browser_credentials(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase
) -> None:
    key = await factories.make_api_key(session)
    client.cookies.clear()
    response = await client.post(case.url, headers={"Zotero-API-Key": key.key}, json=case.body())
    assert response.status_code == 401


async def test_csrf_is_required(client: httpx2.AsyncClient, case: MergeCase) -> None:
    response = await client.post(
        case.url, headers={"If-Unmodified-Since-Version": "10"}, json=case.body()
    )
    assert response.status_code == 403
    await unchanged(client, case)


@pytest.mark.parametrize(
    "change",
    [
        {"others": []},
        {"others": ["MISSING2"]},
        {"master": "MISSING2"},
        {"fields": {"deleted": True}},
        {"fields": {"tags": []}},
        {"fields": {"itemType": "note"}},
        {"fields": {"nonsense": "x"}},
        {"fields": {"creators": [{"creatorType": "invented", "name": "x"}]}},
        {"tags": []},
        {"version": 10},
    ],
)
async def test_invalid_input_leaves_the_whole_library_untouched(
    client: httpx2.AsyncClient, case: MergeCase, change: dict[str, Any]
) -> None:
    response = await client.post(case.url, headers=headers(client), json=case.body(**change))
    assert response.status_code in {400, 404}
    await unchanged(client, case)


@pytest.mark.parametrize("kind", ["self", "repeated", "trashed", "type", "child", "foreign"])
async def test_selection_is_validated_as_a_whole(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase, kind: str
) -> None:
    body = case.body(fields={"title": "Lost"})
    status = 400
    if kind == "self":
        body["others"] = [case.master.key]
    elif kind == "repeated":
        body["others"] *= 2
    elif kind == "trashed":
        case.other.deleted = True
    elif kind == "type":
        case.other.item_type = "journalArticle"
    elif kind == "child":
        body["others"] = [case.note.key]
    elif kind == "foreign":
        await factories.make_user(session, user_id=2, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == 2))
        assert theirs is not None
        foreign = await factories.make_item(session, theirs)
        body["others"] = [foreign.key]
        status = 404
    await session.commit()
    response = await client.post(case.url, headers=headers(client), json=body)
    assert response.status_code == status
    await session.refresh(case.library)
    await session.refresh(case.master)
    assert case.library.version == 10
    assert case.master.field_values()["title"] == "Original"


@pytest.mark.parametrize("permission", ["read", "add", "own", "inherit"])
async def test_group_permissions_activity_and_authorship(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase, permission: str
) -> None:
    await factories.make_user(session, user_id=2, username="grace")
    library = await factories.make_group(session, owner_id=2, members={1: "member"})
    group_case = await seed(session, library)
    user = await session.get(User, 1)
    assert user is not None
    await groups.set_permission(session, library, user, permission)
    # For own, the note belongs to someone else: refuse the complete merge.
    group_case.master.created_by_user_id = group_case.other.created_by_user_id = 1
    group_case.note.created_by_user_id = 2 if permission == "own" else 1
    await session.commit()
    response = await client.post(
        group_case.url, headers=headers(client), json=group_case.body(fields={"title": "Chosen"})
    )
    if permission != "inherit":
        assert response.status_code == 403
        await session.refresh(group_case.master)
        await session.refresh(library)
        assert group_case.master.field_values()["title"] == "Original"
        assert library.version == 10
        assert list(await session.scalars(select(GroupActivity))) == []
    else:
        assert response.status_code == 200
        activity = (
            await session.scalars(
                select(GroupActivity).options(selectinload(GroupActivity.objects))
            )
        ).one()
        assert activity.count == 3
        assert activity.actor_id == 1
        assert {obj.object_key for obj in activity.objects} == {
            group_case.master.key,
            group_case.other.key,
            group_case.note.key,
        }
        await session.refresh(group_case.note)
        assert group_case.note.last_modified_by_user_id == 1


async def test_somebody_elses_library_is_refused(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase
) -> None:
    await factories.make_user(session, user_id=2, username="grace")
    theirs = await session.scalar(select(Library).where(Library.owner_id == 2))
    assert theirs is not None
    foreign = await seed(session, theirs)
    response = await client.post(foreign.url, headers=headers(client), json=foreign.body())
    assert response.status_code == 403


async def test_a_write_while_waiting_for_the_lock_invalidates_the_merge(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    case: MergeCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = await factories.make_api_key(session)
    entered, resume = asyncio.Event(), asyncio.Event()
    original = writes.lock_library
    first = True

    async def held(write_session: AsyncSession, library: Library) -> Library:
        nonlocal first
        if first:
            first = False
            entered.set()
            await resume.wait()
        return await original(write_session, library)

    monkeypatch.setattr(writes, "lock_library", held)
    task = asyncio.create_task(
        client.post(case.url, headers=headers(client), json=case.body(fields={"title": "Stale"}))
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        edited = await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[
                {
                    "key": case.other.key,
                    "version": 1,
                    "title": "Desktop's new title",
                }
            ],
        )
        assert edited.status_code == 200
        assert edited.json()["failed"] == {}
        resume.set()
        response = await asyncio.wait_for(task, 10)
        assert response.status_code == 412
    finally:
        resume.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await session.refresh(case.other)
    await session.refresh(case.master)
    assert not case.other.deleted
    assert case.other.field_values()["title"] == "Desktop's new title"
    assert case.master.field_values()["title"] == "Original"
