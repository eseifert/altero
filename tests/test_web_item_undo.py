"""Browser undo reverses only the committed errand, at its exact watermark."""

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import CollectionItem, GroupActivity, Item, Library, User
from altero.services import groups, writes
from tests import factories
from tests.test_web_routes import csrf_headers, register


@dataclass
class Case:
    library: Library
    first: Item
    second: Item

    @property
    def url(self) -> str:
        return f"/web/libraries/{self.library.id}/items"

    async def write(self, client: httpx2.AsyncClient, **changes: Any) -> httpx2.Response:
        response = await client.patch(
            self.url,
            headers=csrf_headers(client),
            json={"items": [self.first.key, self.second.key], **changes},
        )
        assert response.status_code == 200, response.text
        return response

    async def read(self, client: httpx2.AsyncClient, key: str) -> dict[str, Any]:
        return (await client.get(f"{self.url}/{key}")).json()


@pytest.fixture
async def case(client: httpx2.AsyncClient, session: AsyncSession) -> Case:
    assert (await register(client)).status_code == 201
    library = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert library is not None
    first = await factories.make_item(session, library, fields={"title": "Keep this title"})
    second = await factories.make_item(session, library, fields={"title": "Already trashed"})
    second.deleted = True
    library.version = 10
    await session.commit()
    return Case(library, first, second)


async def undo(client: httpx2.AsyncClient, case: Case, snapshot: dict[str, Any]) -> httpx2.Response:
    return await client.post(
        f"{case.url}/undo",
        headers=csrf_headers(client) | {"If-Unmodified-Since-Version": str(snapshot["version"])},
        json={"items": snapshot["items"]},
    )


async def test_trash_undo_leaves_previously_trashed_items_alone(
    client: httpx2.AsyncClient, case: Case
) -> None:
    response = await case.write(client, deleted=True)
    snapshot = response.json()["undo"]
    assert snapshot == {"version": 11, "items": [{"key": case.first.key, "deleted": False}]}
    restored = await undo(client, case, snapshot)
    assert restored.status_code == 200, restored.text
    assert restored.headers["Last-Modified-Version"] == "12"
    first = await case.read(client, case.first.key)
    assert not first["data"].get("deleted")
    assert first["version"] == 12
    assert first["data"]["title"] == "Keep this title"
    assert (await case.read(client, case.second.key))["data"]["deleted"] == 1
    # A double click, retry or older toast cannot apply it twice.
    assert (await undo(client, case, snapshot)).status_code == 412


async def test_filing_undo_restores_each_items_actual_memberships(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    papers = await factories.make_collection(session, case.library, name="Papers")
    books = await factories.make_collection(session, case.library, name="Books")
    session.add_all(
        [
            CollectionItem(item_id=case.first.id, collection_id=papers.id),
            CollectionItem(item_id=case.second.id, collection_id=books.id),
        ]
    )
    await session.commit()
    response = await case.write(client, addCollections=[books.key], removeCollections=[papers.key])
    snapshot = response.json()["undo"]
    # The second item was already filed there; undo must leave it alone.
    assert snapshot["items"] == [{"key": case.first.key, "collections": [papers.key]}]
    assert (await undo(client, case, snapshot)).status_code == 200
    assert (await case.read(client, case.first.key))["data"]["collections"] == [papers.key]
    second = await case.read(client, case.second.key)
    assert second["data"]["collections"] == [books.key]
    assert second["data"]["deleted"] == 1


async def test_combined_errand_undo_restores_only_the_fields_changed(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    papers = await factories.make_collection(session, case.library, name="Papers")
    response = await case.write(client, addCollections=[papers.key], deleted=True)
    snapshot = response.json()["undo"]
    assert snapshot["items"] == [
        {"key": case.first.key, "collections": [], "deleted": False},
        {"key": case.second.key, "collections": []},
    ]
    assert (await undo(client, case, snapshot)).status_code == 200
    first = await case.read(client, case.first.key)
    assert first["data"]["collections"] == []
    assert not first["data"].get("deleted")
    assert (await case.read(client, case.second.key))["data"]["deleted"] == 1


@pytest.mark.parametrize(
    ("version", "status"), [(None, 428), ("9", 412), ("999", 412), ("bad", 400)]
)
async def test_undo_requires_the_exact_library_version(
    client: httpx2.AsyncClient, case: Case, version: str | None, status: int
) -> None:
    headers = csrf_headers(client)
    if version is not None:
        headers["If-Unmodified-Since-Version"] = version
    response = await client.post(
        f"{case.url}/undo",
        headers=headers,
        json={"items": [{"key": case.first.key, "deleted": True}]},
    )
    assert response.status_code == status
    assert (await case.read(client, case.first.key))["version"] == 1


async def test_a_later_write_cannot_be_overwritten_by_undo(
    client: httpx2.AsyncClient, case: Case
) -> None:
    snapshot = (await case.write(client, deleted=True)).json()["undo"]
    await case.write(client, deleted=False)
    assert (await undo(client, case, snapshot)).status_code == 412
    assert not (await case.read(client, case.second.key))["data"].get("deleted")


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "MISSING2", "deleted": False},
        {"key": "MISSING2", "collections": ["MISSING2"]},
    ],
)
async def test_invalid_member_rolls_back_the_whole_undo(
    client: httpx2.AsyncClient, case: Case, bad: dict[str, Any]
) -> None:
    snapshot = (await case.write(client, deleted=True)).json()["undo"]
    snapshot["items"].append(bad)
    assert (await undo(client, case, snapshot)).status_code == 404
    assert (await case.read(client, case.first.key))["data"]["deleted"] == 1
    libraries = (await client.get("/web/libraries")).json()
    assert next(row["version"] for row in libraries if row["id"] == case.library.id) == 11


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"key": "FIRST222"}],
        [{"key": "FIRST222", "deleted": None}],
        [{"key": "FIRST222", "title": "Unexpected"}],
        [{"key": "FIRST222", "deleted": False}, {"key": "FIRST222", "deleted": True}],
    ],
)
async def test_empty_duplicate_or_unrelated_changes_are_refused(
    client: httpx2.AsyncClient, case: Case, changes: list[dict[str, Any]]
) -> None:
    response = await undo(client, case, {"version": 10, "items": changes})
    assert response.status_code == 400


async def test_undo_requires_cookie_and_csrf(client: httpx2.AsyncClient, case: Case) -> None:
    body = {"items": [{"key": case.first.key, "deleted": True}]}
    headers = {"If-Unmodified-Since-Version": "10"}
    assert (await client.post(f"{case.url}/undo", json=body, headers=headers)).status_code == 403
    client.cookies.clear()
    assert (await client.post(f"{case.url}/undo", json=body, headers=headers)).status_code == 401


async def test_a_noop_offers_no_inverse(client: httpx2.AsyncClient, case: Case) -> None:
    await case.write(client, deleted=True)
    assert (await case.write(client, deleted=True)).json()["undo"]["items"] == []


async def test_bad_collection_rolls_back_an_earlier_restoration(
    client: httpx2.AsyncClient, case: Case
) -> None:
    snapshot = (await case.write(client, deleted=True)).json()["undo"]
    snapshot["items"].append({"key": case.second.key, "collections": ["MISSING2"]})
    assert (await undo(client, case, snapshot)).status_code == 409
    assert (await case.read(client, case.first.key))["data"]["deleted"] == 1
    assert (await case.read(client, case.first.key))["version"] == 11


async def test_a_child_note_keeps_its_parent_and_html(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    child = await factories.make_item(
        session,
        case.library,
        item_type="note",
        parent=case.first,
        fields={"note": "<p>Keep my note</p>"},
    )
    response = await client.patch(
        case.url,
        headers=csrf_headers(client),
        json={"items": [child.key], "deleted": True},
    )
    assert (await undo(client, case, response.json()["undo"])).status_code == 200
    restored = await case.read(client, child.key)
    assert restored["data"]["note"] == "<p>Keep my note</p>"
    assert restored["data"]["parentItem"] == case.first.key
    assert not restored["data"].get("deleted")


@pytest.mark.parametrize("permission", ["read", "add", "own", "inherit"])
async def test_undo_rechecks_group_permissions_and_records_one_activity(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case, permission: str
) -> None:
    await factories.make_user(session, user_id=2, username="grace")
    library = await factories.make_group(session, owner_id=2, members={1: "member"})
    first = await factories.make_item(session, library, deleted=True)
    second = await factories.make_item(session, library, deleted=True)
    first.created_by_user_id = 1
    second.created_by_user_id = 2
    library.version = 10
    user = await session.get(User, 1)
    assert user is not None
    await groups.set_permission(session, library, user, permission)
    await session.commit()
    group_case = Case(library, first, second)
    response = await undo(
        client,
        group_case,
        {
            "version": 10,
            "items": [
                {"key": first.key, "deleted": False},
                {"key": second.key, "deleted": False},
            ],
        },
    )
    if permission in {"inherit", "add"}:
        assert response.status_code == 200
        activity = (await session.scalars(select(GroupActivity))).one()
        assert activity.count == 2
        assert activity.actor_id == 1
        assert {row["version"] for row in response.json()["items"]} == {11}
    else:
        assert response.status_code == 403
        await session.refresh(first)
        await session.refresh(library)
        assert first.deleted
        assert library.version == 10
        assert list(await session.scalars(select(GroupActivity))) == []


async def test_another_librarys_item_cannot_be_restored(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    await factories.make_user(session, user_id=2, username="grace")
    library = await session.scalar(select(Library).where(Library.owner_id == 2))
    assert library is not None
    foreign = await factories.make_item(session, library, deleted=True)
    response = await undo(
        client,
        case,
        {
            "version": 10,
            "items": [
                {"key": foreign.key, "deleted": False},
            ],
        },
    )
    assert response.status_code == 404


async def test_a_write_while_waiting_for_the_lock_invalidates_undo(
    client: httpx2.AsyncClient, case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = (await case.write(client, deleted=True)).json()["undo"]
    entered, resume = asyncio.Event(), asyncio.Event()
    original = writes.lock_library
    first = True

    async def held(session: AsyncSession, library: Library) -> Library:
        nonlocal first
        if first:
            first = False
            entered.set()
            await resume.wait()
        return await original(session, library)

    monkeypatch.setattr(writes, "lock_library", held)
    task = asyncio.create_task(undo(client, case, snapshot))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await case.write(client, deleted=False)
        resume.set()
        assert (await asyncio.wait_for(task, 10)).status_code == 412
    finally:
        resume.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert (await case.read(client, case.first.key))["version"] == 12
