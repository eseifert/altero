"""Deleting what nobody asked to keep.

The trash is the sharp one. Deleting an item out of it is a write like any
other: it takes a new library version and it records the deletion, because a
syncing client learns that something went from `/deleted?since=`, and a server
that removed rows quietly would leave every client holding an item that no
longer exists and no way to find out.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import (
    ActivityKind,
    GroupActivity,
    Item,
    LibraryType,
    StorageDownload,
    StorageUpload,
    WebSession,
)
from altero.services import retention
from altero.services.auth import get_library
from tests.factories import make_api_key, make_group, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

#: Everything off. Each test turns on the one thing it is about, so a sweep
#: cannot pass by deleting something the test never mentioned.
NOTHING = {"trashRetentionDays": 0, "activityRetentionDays": 0, "uploadRetentionHours": 0}


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def trashed_long_ago(session: AsyncSession, library, *, days: int) -> Item:
    """An item in the trash that the server last saw ``days`` ago."""
    item = await make_item(session, library, deleted=True)
    item.server_date_modified = now() - timedelta(days=days)
    await session.commit()
    return item


class TestTheTrash:
    async def test_an_item_past_the_period_is_deleted(self, session: AsyncSession) -> None:
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        await trashed_long_ago(session, library, days=40)

        report = await retention.sweep(session, NOTHING | {"trashRetentionDays": 30})

        assert report.items_deleted == 1
        assert (await session.scalar(select(Item).where(Item.library_id == library.id))) is None

    async def test_an_item_inside_the_period_is_left_alone(self, session: AsyncSession) -> None:
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        await trashed_long_ago(session, library, days=10)

        report = await retention.sweep(session, NOTHING | {"trashRetentionDays": 30})

        assert report.items_deleted == 0

    async def test_an_item_that_is_not_in_the_trash_is_never_touched(
        self, session: AsyncSession
    ) -> None:
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        old = await make_item(session, library)
        old.server_date_modified = now() - timedelta(days=4000)
        await session.commit()

        report = await retention.sweep(session, NOTHING | {"trashRetentionDays": 1})

        assert report.items_deleted == 0

    async def test_zero_deletes_nothing(self, session: AsyncSession) -> None:
        """The default, and what an instance upgraded into this must do."""
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        await trashed_long_ago(session, library, days=4000)

        report = await retention.sweep(session, NOTHING)

        assert report.items_deleted == 0

    async def test_a_dry_run_reports_without_deleting(self, session: AsyncSession) -> None:
        """So an operator can see what a period would do before setting it."""
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        await trashed_long_ago(session, library, days=40)

        report = await retention.sweep(session, NOTHING | {"trashRetentionDays": 30}, dry_run=True)

        assert report.items_deleted == 1
        assert await session.scalar(select(Item).where(Item.library_id == library.id))

    async def test_the_library_version_moves_exactly_once(self, session: AsyncSession) -> None:
        """However many items went. One sweep of one library is one write."""
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        for _ in range(3):
            await trashed_long_ago(session, library, days=40)
        before = library.version

        await retention.sweep(session, NOTHING | {"trashRetentionDays": 30})

        await session.refresh(library)
        assert library.version == before + 1

    async def test_it_records_the_deletion_for_every_group_member(
        self, session: AsyncSession
    ) -> None:
        """Nobody did it, so the activity has no actor -- and still happened."""
        await make_user(session)
        library = await make_group(session, group_id=100, owner_id=1)
        await trashed_long_ago(session, library, days=40)

        await retention.sweep(session, NOTHING | {"trashRetentionDays": 30})

        activity = await session.scalar(select(GroupActivity))
        assert activity is not None
        assert activity.kind == ActivityKind.ITEMS_DELETED
        assert activity.actor_id is None


class TestWhatAClientIsTold:
    async def test_a_syncing_client_learns_the_item_is_gone(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The whole reason this goes through the ordinary delete path.

        A row removed without a deletion record leaves every client that had
        synced holding an item this server no longer has, with nothing to tell
        them apart from a full re-download.
        """
        await make_user(session)
        await make_api_key(session, key=KEY)
        library = await get_library(session, LibraryType.USER, 1)
        item = await trashed_long_ago(session, library, days=40)
        gone = item.key

        await retention.sweep(session, NOTHING | {"trashRetentionDays": 30})

        response = await client.get("/users/1/deleted?since=0", headers=AUTH)
        assert gone in response.json()["items"]


class TestHousekeeping:
    async def test_an_upload_whose_bytes_never_arrived_is_forgotten(
        self, session: AsyncSession
    ) -> None:
        await make_user(session)
        library = await get_library(session, LibraryType.USER, 1)
        item = await make_item(session, library, item_type="attachment")
        session.add(
            StorageUpload(
                key="abandoned",
                item_id=item.id,
                library_id=library.id,
                md5="0" * 32,
                zip_md5=None,
                filename="paper.pdf",
                filesize=10,
                mtime=0,
                created=now() - timedelta(hours=48),
            )
        )
        await session.commit()

        report = await retention.sweep(session, NOTHING | {"uploadRetentionHours": 24})

        assert report.uploads == 1
        assert (await session.scalar(select(StorageUpload))) is None

    async def test_delivered_activity_older_than_the_period_goes(
        self, session: AsyncSession
    ) -> None:
        await make_user(session)
        library = await make_group(session, group_id=100, owner_id=1)
        session.add(
            GroupActivity(
                library_id=library.id,
                kind=ActivityKind.ITEMS_CHANGED,
                count=1,
                created=now() - timedelta(days=400),
                flushed=now() - timedelta(days=400),
            )
        )
        await session.commit()

        report = await retention.sweep(session, NOTHING | {"activityRetentionDays": 365})

        assert report.activity == 1
        assert (await session.scalar(select(GroupActivity))) is None

    async def test_activity_nobody_has_been_told_about_yet_stays(
        self, session: AsyncSession
    ) -> None:
        """Undelivered is not old, however long ago it happened.

        A sweep that took it would silently unsubscribe everybody whose digest
        was waiting on a mail relay that was down.
        """
        await make_user(session)
        library = await make_group(session, group_id=100, owner_id=1)
        session.add(
            GroupActivity(
                library_id=library.id,
                kind=ActivityKind.ITEMS_CHANGED,
                count=1,
                created=now() - timedelta(days=400),
                flushed=None,
            )
        )
        await session.commit()

        report = await retention.sweep(session, NOTHING | {"activityRetentionDays": 365})

        assert report.activity == 0

    async def test_an_expired_session_is_swept_without_being_asked(
        self, session: AsyncSession
    ) -> None:
        """No period of its own: it expired, so it is already nobody's session."""
        user = await make_user(session)
        session.add(
            WebSession(
                token_hash="dead",
                user_id=user.id,
                expires=now() - timedelta(days=1),
            )
        )
        await session.commit()

        report = await retention.sweep(session, NOTHING)

        assert report.sessions == 1
        assert (await session.scalar(select(WebSession))) is None

    async def test_a_spent_download_permission_is_swept_without_being_asked(
        self, session: AsyncSession
    ) -> None:
        """Same reasoning: past its five minutes it opens nothing.

        A library syncing its files asks for one of these per attachment, so
        without the sweep the table grows for as long as the instance runs.
        """
        user = await make_user(session)
        library = await get_library(session, LibraryType.USER, user.id)
        item = await make_item(session, library, key="AAAA2345", item_type="attachment")
        session.add(
            StorageDownload(
                key="spent",
                item_id=item.id,
                library_id=library.id,
                md5="d41d8cd98f00b204e9800998ecf8427e",
                expires=now() - timedelta(minutes=1),
            )
        )
        await session.commit()

        report = await retention.sweep(session, NOTHING)

        assert report.downloads == 1
        assert (await session.scalar(select(StorageDownload))) is None


@pytest.mark.parametrize("period", ["trashRetentionDays", "activityRetentionDays"])
async def test_an_empty_instance_sweeps_cleanly(session: AsyncSession, period: str) -> None:
    report = await retention.sweep(session, NOTHING | {period: 1})

    assert report.items_deleted == 0
    assert report.libraries == 0


class TestWhatTheSweepWillNotTouch:
    async def test_a_file_nothing_references_survives(
        self, session: AsyncSession, settings
    ) -> None:
        """Reported on the storage screen, never swept.

        Bytes reach the disk before the item row that refers to them is
        committed, so a sweep that deleted unreferenced files would race every
        upload in flight.
        """
        from altero.services import storage

        await make_user(session)
        path = storage.file_path(settings.storage_path, "0" * 32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"nobody's file")

        await retention.sweep(
            session,
            {"trashRetentionDays": 1, "activityRetentionDays": 1, "uploadRetentionHours": 1},
        )

        assert path.is_file()
