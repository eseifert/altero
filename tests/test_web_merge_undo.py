"""Merge undo restores the stored graph, never a browser-supplied replacement."""

from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, User
from altero.services import groups, items
from tests import factories
from tests.test_merge import set_relations
from tests.test_web_merge import MergeCase, headers, seed
from tests.test_web_routes import csrf_headers, register


@pytest.fixture
async def case(client: httpx2.AsyncClient, session: AsyncSession) -> MergeCase:
    assert (await register(client)).status_code == 201
    library = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert library is not None
    return await seed(session, library)


async def read(client: httpx2.AsyncClient, case: MergeCase, key: str) -> dict[str, Any]:
    response = await client.get(f"/web/libraries/{case.library.id}/items/{key}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def merge(client: httpx2.AsyncClient, case: MergeCase) -> dict[str, Any]:
    response = await client.post(
        case.url, headers=headers(client), json=case.body(fields={"title": "Chosen", "extra": ""})
    )
    assert response.status_code == 200, response.text
    assert response.json()["undo"] == {"version": 11, "merge": True}
    return response.json()


async def undo(client: httpx2.AsyncClient, case: MergeCase, version: str = "11") -> httpx2.Response:
    return await client.post(f"{case.url}/undo", headers=headers(client, version))


async def test_restores_fields_dates_children_and_incoming_links_in_one_new_version(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase
) -> None:
    referring = await factories.make_item(session, case.library)
    await set_relations(
        session, referring, ("dc:relation", items.item_uri(case.library, case.other.key))
    )
    originals = {
        item.key: await read(client, case, item.key)
        for item in (case.master, case.other, case.note, referring)
    }
    await merge(client, case)
    assert (await read(client, case, case.note.key))["parentItem"] == case.master.key
    response = await undo(client, case)
    assert response.status_code == 200, response.text
    assert response.headers["Last-Modified-Version"] == "12"
    assert {item["version"] for item in response.json()["items"]} == {12}
    for key, before in originals.items():
        after = await read(client, case, key)
        for name in ("version", "dateModified"):
            before.pop(name, None)
            after.pop(name, None)
        assert after == before
    assert (await undo(client, case)).status_code == 412


@pytest.mark.parametrize(
    ("version", "status"), [(None, 428), ("10", 412), ("12", 412), ("bad", 400)]
)
async def test_undo_requires_the_exact_committed_library_version(
    client: httpx2.AsyncClient, case: MergeCase, version: str | None, status: int
) -> None:
    await merge(client, case)
    response = await client.post(
        f"{case.url}/undo",
        headers=csrf_headers(client) if version is None else headers(client, version),
    )
    assert response.status_code == status
    assert (await read(client, case, case.master.key))["title"] == "Chosen"


async def test_any_later_write_invalidates_undo(
    client: httpx2.AsyncClient, case: MergeCase
) -> None:
    await merge(client, case)
    changed = await client.patch(
        f"/web/libraries/{case.library.id}/items/{case.master.key}",
        headers=csrf_headers(client),
        json={"version": 11, "fields": {"title": "Later edit"}},
    )
    assert changed.status_code == 200
    assert (await undo(client, case, "12")).status_code == 412
    assert (await read(client, case, case.master.key))["title"] == "Later edit"


@pytest.mark.parametrize("fields", [{}, {"title": "Chosen"}])
async def test_only_effective_relation_changes_preserve_the_modification_date(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase, fields: dict[str, str]
) -> None:
    case.master.date_added = case.other.date_added
    await session.commit()
    response = await client.post(case.url, headers=headers(client), json=case.body(fields=fields))
    assert response.status_code == 200
    await session.refresh(case.master)
    case.master.date_modified = datetime(2000, 1, 1)
    await session.commit()
    assert (await undo(client, case)).status_code == 200
    modified = (await read(client, case, case.master.key))["dateModified"]
    assert (modified == "2000-01-01T00:00:00Z") is (not fields)


async def test_cookie_and_csrf_are_required(client: httpx2.AsyncClient, case: MergeCase) -> None:
    await merge(client, case)
    assert (
        await client.post(f"{case.url}/undo", headers={"If-Unmodified-Since-Version": "11"})
    ).status_code == 403
    client.cookies.clear()
    assert (await undo(client, case)).status_code == 401


@pytest.mark.parametrize("permission", ["read", "add", "own", "inherit"])
async def test_current_item_permissions_apply_to_the_whole_reversal(
    client: httpx2.AsyncClient, session: AsyncSession, permission: str
) -> None:
    assert (await register(client)).status_code == 201
    await factories.make_user(session, user_id=2, username="grace")
    library = await factories.make_group(session, owner_id=2, members={1: "member"})
    case = await seed(session, library)
    case.master.created_by_user_id = case.other.created_by_user_id = 1
    case.note.created_by_user_id = 2
    await session.commit()
    await merge(client, case)
    user = await session.get(User, 1)
    assert user is not None
    await groups.set_permission(session, library, user, permission)
    await session.commit()
    response = await undo(client, case)
    assert response.status_code == (200 if permission in {"add", "inherit"} else 403), response.text
    if permission in {"read", "own"}:
        assert (await read(client, case, case.master.key))["title"] == "Chosen"
        # A refused reversal has not consumed the stored snapshot.
        await groups.set_permission(session, library, user, "inherit")
        await session.commit()
        assert (await undo(client, case)).status_code == 200


async def test_snapshot_is_private_expires_and_is_cleared_with_the_library(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase
) -> None:
    from altero.models import MergeUndo
    from altero.services import mergeundo, retention, transfer

    await merge(client, case)
    snapshot = await session.get(MergeUndo, case.library.id)
    assert snapshot is not None
    await factories.make_user(session, user_id=2, username="grace")
    snapshot = await session.get(MergeUndo, case.library.id)
    assert snapshot is not None
    snapshot.user_id = 2
    await session.commit()
    assert (await undo(client, case)).status_code == 404
    snapshot.user_id = 1
    snapshot.expires = mergeundo.now() - timedelta(seconds=1)
    await session.commit()
    assert (await undo(client, case)).status_code == 404
    report = await retention.sweep(session, {}, dry_run=True)
    assert report.merge_undos == 1
    assert await session.get(MergeUndo, case.library.id) is not None
    report = await retention.sweep(session, {})
    assert report.merge_undos == 1
    assert await session.get(MergeUndo, case.library.id) is None
    assert "expired merge undos" in retention.describe(report)
    session.add(
        MergeUndo(
            library_id=case.library.id, user_id=1, version=11, patches=[], expires=mergeundo.now()
        )
    )
    await session.commit()
    await transfer.clear_library(session, case.library)
    await session.commit()
    assert await session.get(MergeUndo, case.library.id) is None


async def test_a_swept_snapshot_can_be_replaced_even_when_its_old_row_is_cached(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase
) -> None:
    from altero.models import MergeUndo
    from altero.services import mergeundo, retention, writes

    await merge(client, case)
    old = await session.get(MergeUndo, case.library.id)
    assert old is not None
    old.expires = mergeundo.now() - timedelta(seconds=1)
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as sweeper:
        assert (await retention.sweep(sweeper, {})).merge_undos == 1
    await writes.lock_library(session, case.library)
    await writes.bump_library_version(session, case.library)
    patches = [{"key": case.master.key, "deleted": False}]
    await mergeundo.remember(session, case.library, 1, patches)
    await session.commit()
    replacement = await session.get(MergeUndo, case.library.id)
    assert replacement is not None
    assert replacement.version == 12
    assert replacement.patches == patches


async def test_pdf_graph_tags_collections_and_promoted_notes_are_restored(
    client: httpx2.AsyncClient, session: AsyncSession, case: MergeCase, settings
) -> None:
    from altero.models import CollectionItem, FullText, MergeUndo
    from tests.test_merge_attachments import attachment

    await factories.make_user(session, user_id=2, username="grace")
    group = await factories.make_group(session, owner_id=2, members={1: "member"})
    case = await seed(session, group)
    first = await factories.make_collection(session, case.library, name="First")
    second = await factories.make_collection(session, case.library, name="Second")
    session.add_all(
        [
            CollectionItem(collection_id=first.id, item_id=case.master.id),
            CollectionItem(collection_id=second.id, item_id=case.other.id),
        ]
    )
    await factories.tag_item(session, case.library, case.master, "Manual", tag_type=0)
    await factories.tag_item(session, case.library, case.other, "Automatic", tag_type=1)
    kept = await attachment(
        session, case.library, case.master, settings.storage_path, note="<p>Master note</p>"
    )
    removed = await attachment(
        session, case.library, case.other, settings.storage_path, note="<p>Duplicate note</p>"
    )
    annotation = await factories.make_item(
        session,
        case.library,
        item_type="annotation",
        parent=removed,
        fields={
            "annotationType": "highlight",
            "annotationText": "Keep annotation",
            "annotationColor": "#ffd400",
            "annotationSortIndex": "00000|000000|00000",
            "annotationPosition": '{"pageIndex":0,"rects":[[0,0,10,10]]}',
        },
    )
    session.add(
        FullText(
            item_id=removed.id, library_id=case.library.id, version=1, content="Indexed original"
        )
    )
    await session.commit()
    keys = [item.key for item in (case.master, case.other, case.note, kept, removed, annotation)]
    original = {key: await read(client, case, key) for key in keys}
    answer = await merge(client, case)
    generated = [item for item in answer["items"] if item["key"] not in keys]
    assert len(generated) == 1
    assert (await read(client, case, annotation.key))["parentItem"] == kept.key
    user = await session.get(User, 1)
    assert user is not None
    await groups.set_permission(session, group, user, "add")
    await session.commit()
    # This reversal must also trash the promoted note. Add-only permission
    # refuses that final write and rolls back every earlier restoration.
    assert (await undo(client, case)).status_code == 403
    assert (await read(client, case, case.master.key))["title"] == "Chosen"
    assert (await read(client, case, annotation.key))["parentItem"] == kept.key
    await groups.set_permission(session, group, user, "inherit")
    await session.commit()
    assert (await undo(client, case)).status_code == 200
    for key, before in original.items():
        after = await read(client, case, key)
        for name in ("version", "dateModified"):
            before.pop(name, None)
            after.pop(name, None)
        assert after == before
    assert (await read(client, case, generated[0]["key"]))["deleted"] == 1
    for item in (kept, removed):
        response = await client.get(
            f"/web/libraries/{case.library.id}/items/{item.key}/file", follow_redirects=True
        )
        assert response.status_code == 200
        from tests.test_pdfmerge import pdf_bytes

        assert response.content == pdf_bytes()
    assert (
        await session.scalar(select(FullText.content).where(FullText.item_id == removed.id))
    ) == "Indexed original"
    assert await session.get(MergeUndo, case.library.id) is None
