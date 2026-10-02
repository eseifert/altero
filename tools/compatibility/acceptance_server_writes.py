"""Browser writes and the real retention service reach offline desktop caches."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from altero.models import Library, User
from altero.services import retention, websessions
from tools.compatibility.acceptance_runtime import AcceptanceRun


async def server_writes(run: AcceptanceRun) -> None:
    await run.phase(
        "A",
        [
            dict(
                action="create",
                key="BRNWSER2",
                data=dict(itemType="book", title="Browser changes", tags=[dict(tag="before")]),
            )
        ],
        files=False,
    )
    await run.phase("B", files=False)
    assert run.server.session_factory is not None
    async with run.server.session_factory() as session:
        user = await session.get(User, 1)
        assert user is not None
        token, _ = await websessions.create(session, user)
        library = await session.scalar(select(Library).where(Library.owner_id == 1))
        assert library is not None
        library_id = library.id
    async with httpx.AsyncClient(
        base_url=run.server.url,
        cookies={"altero_session": token, "altero_csrf": "acceptance-csrf"},
        headers={"X-CSRF-Token": "acceptance-csrf"},
    ) as browser:
        collection = await browser.post(
            f"/web/libraries/{library_id}/collections", json={"name": "Browser filing"}
        )
        collection.raise_for_status()
        key = collection.json()["key"]
        filed = await browser.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": ["BRNWSER2"], "addCollections": [key]},
        )
        filed.raise_for_status()
        renamed = await browser.patch(
            f"/web/libraries/{library_id}/tags/before", json={"tag": "after"}
        )
        renamed.raise_for_status()
        left, right = await run.phase("A", files=False), await run.phase("B", files=False)
        await run.converged(left, right)
        assert right["items"][0]["collections"] == [key]
        assert right["items"][0]["tags"] == [dict(tag="after")]
        trashed = await browser.patch(
            f"/web/libraries/{library_id}/items", json={"items": ["BRNWSER2"], "deleted": True}
        )
        trashed.raise_for_status()
    async with run.server.session_factory() as session:
        # Time is an input to the retention service; no stored timestamp is forced.
        report = await retention.sweep(
            session,
            {"trashRetentionDays": 1},
            now=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=2),
        )
        assert report.items_deleted == 1
    left, right = await run.phase("A", files=False), await run.phase("B", files=False)
    await run.converged(left, right)
    assert not left["items"], "Retention left stale items in desktop persistence"
    assert "BRNWSER2" in (await run.request("GET", "/users/1/deleted?since=0")).json()["items"]
    await run.settled(files=False)
