"""Copy undo trashes only the new destination records at their committed version."""

from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import GroupActivity, Item, Library, User
from altero.services import groups
from tests import factories
from tests.test_web_routes import csrf_headers, register


@dataclass
class Case:
    source: Library
    target: Library
    original: Item
    other: Item
    kept: Item

    def url(self, library: Library) -> str:
        return f"/web/libraries/{library.id}/items"

    async def copy(self, client: httpx2.AsyncClient, **extra: Any) -> httpx2.Response:
        response = await client.post(
            f"{self.url(self.source)}/copy",
            headers=csrf_headers(client),
            json={"items": [self.original.key, self.other.key], "library": self.target.id, **extra},
        )
        assert response.status_code == 201, response.text
        return response

    async def undo(self, client: httpx2.AsyncClient, snapshot: dict[str, Any]) -> httpx2.Response:
        return await client.post(
            f"{self.url(self.target)}/undo",
            headers=csrf_headers(client)
            | {"If-Unmodified-Since-Version": str(snapshot["version"])},
            json={"items": snapshot["items"]},
        )


@pytest.fixture
async def case(client: httpx2.AsyncClient, session: AsyncSession) -> Case:
    assert (await register(client)).status_code == 201
    source = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert source is not None
    await factories.make_user(session, user_id=2, username="grace")
    target = await factories.make_group(session, owner_id=2, members={1: "member"})
    original = await factories.make_item(session, source, fields={"title": "Original"})
    other = await factories.make_item(session, source, fields={"title": "Other original"})
    kept = await factories.make_item(session, target, fields={"title": "Already here"})
    kept.created_by_user_id = 2
    source.version = 10
    target.version = 20
    await session.commit()
    return Case(source, target, original, other, kept)


async def read(
    client: httpx2.AsyncClient, case: Case, library: Library, key: str
) -> dict[str, Any]:
    return (await client.get(f"{case.url(library)}/{key}")).json()


async def test_undo_trashes_the_copied_selection_in_one_destination_version(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    response = await case.copy(client)
    copied = response.json()["items"]
    snapshot = response.json()["undo"]
    assert snapshot == {
        "version": 21,
        "items": [{"key": item["key"], "deleted": True} for item in copied],
    }
    assert {item["key"] for item in copied}.isdisjoint({case.original.key, case.other.key})
    undone = await case.undo(client, snapshot)
    assert undone.status_code == 200, undone.text
    assert undone.headers["Last-Modified-Version"] == "22"
    assert {item["version"] for item in undone.json()["items"]} == {22}
    assert all(item["data"]["deleted"] == 1 for item in undone.json()["items"])
    for item in (case.original, case.other):
        original = await read(client, case, case.source, item.key)
        assert not original["data"].get("deleted")
        assert original["version"] == 1
    assert not (await read(client, case, case.target, case.kept.key))["data"].get("deleted")
    await session.refresh(case.source)
    assert case.source.version == 10
    activity = list(await session.scalars(select(GroupActivity).order_by(GroupActivity.id)))
    assert [entry.count for entry in activity] == [2, 2]
    assert (await case.undo(client, snapshot)).status_code == 412


async def test_notes_and_registered_bytes_survive_copy_undo_and_restore(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    await factories.make_item(
        session,
        case.source,
        item_type="note",
        parent=case.original,
        fields={"note": "<p>Keep this note</p>"},
    )
    content = b"Bytes shared by the original and the copy"
    uploaded = await client.post(
        f"/web/libraries/{case.source.id}/attachments",
        params={"parentItem": case.original.key, "filename": "keep.txt"},
        headers=csrf_headers(client) | {"Content-Type": "text/plain"},
        content=content,
    )
    assert uploaded.status_code == 201, uploaded.text
    response = await case.copy(client)
    copied = response.json()["items"][0]["key"]
    children = (await client.get(f"{case.url(case.target)}/{copied}/children")).json()["items"]
    note = next(item for item in children if item["data"]["itemType"] == "note")
    attachment = next(item for item in children if item["data"]["itemType"] == "attachment")
    assert (await case.undo(client, response.json()["undo"])).status_code == 200
    # Trash is the undo for deletion; the copied graph can still be restored.
    restored = await client.patch(
        case.url(case.target),
        headers=csrf_headers(client),
        json={"items": [copied], "deleted": False},
    )
    assert restored.status_code == 200
    restored_note = await read(client, case, case.target, note["key"])
    assert restored_note["data"]["parentItem"] == copied
    assert restored_note["data"]["note"] == "<p>Keep this note</p>"
    for library, key in ((case.source, uploaded.json()["key"]), (case.target, attachment["key"])):
        downloaded = await client.get(f"{case.url(library)}/{key}/file", follow_redirects=True)
        assert downloaded.status_code == 200
        assert downloaded.content == content


async def test_a_source_edit_does_not_invalidate_destination_undo(
    client: httpx2.AsyncClient, case: Case
) -> None:
    snapshot = (await case.copy(client)).json()["undo"]
    edited = await client.patch(
        f"{case.url(case.source)}/{case.original.key}",
        headers=csrf_headers(client),
        json={"version": 1, "fields": {"title": "New source title"}},
    )
    assert edited.status_code == 200
    assert (await case.undo(client, snapshot)).status_code == 200
    assert (await read(client, case, case.source, case.original.key))["data"][
        "title"
    ] == "New source title"


async def test_a_destination_edit_invalidates_copy_undo(
    client: httpx2.AsyncClient, case: Case
) -> None:
    copied = await case.copy(client)
    edited = await client.patch(
        f"{case.url(case.target)}/{case.kept.key}",
        headers=csrf_headers(client),
        json={"version": 1, "fields": {"title": "New destination title"}},
    )
    assert edited.status_code == 200
    assert (await case.undo(client, copied.json()["undo"])).status_code == 412
    for item in copied.json()["items"]:
        assert not (await read(client, case, case.target, item["key"]))["data"].get("deleted")


@pytest.mark.parametrize("permission", ["inherit", "own", "add"])
async def test_copy_offers_undo_only_when_the_destination_allows_removal(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case, permission: str
) -> None:
    user = await session.get(User, 1)
    assert user is not None
    await groups.set_permission(session, case.target, user, permission)
    await session.commit()
    response = await case.copy(client)
    if permission == "add":
        assert response.json()["undo"] is None
        # Fabricating the ordinary undo payload cannot bypass the restriction.
        snapshot = {
            "version": 21,
            "items": [{"key": item["key"], "deleted": True} for item in response.json()["items"]],
        }
        assert (await case.undo(client, snapshot)).status_code == 403
    else:
        assert (await case.undo(client, response.json()["undo"])).status_code == 200


async def test_undo_rechecks_permissions_revoked_since_the_copy(
    client: httpx2.AsyncClient, session: AsyncSession, case: Case
) -> None:
    copied = await case.copy(client)
    user = await session.get(User, 1)
    assert user is not None
    await groups.set_permission(session, case.target, user, "read")
    await session.commit()
    assert (await case.undo(client, copied.json()["undo"])).status_code == 403
