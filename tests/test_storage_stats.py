"""What a library costs on disk.

The number zotero.org cannot report and a self-hosted instance can. Files are
stored once per digest, so a file attached in two libraries is on disk once and
in both libraries' accounts: what each library would cost on its own is not
what the instance is paying, and an operator asked to plan for disk needs both.
"""

import os
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services import storage, storagestats
from altero.services.auth import get_library
from tests.factories import make_group, make_item, make_user


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A file store of this test's own, where the settings fixture puts one."""
    return tmp_path / "storage"


def put_file(root: Path, digest: str, body: bytes) -> None:
    """Write bytes into the store the way an upload would."""
    path = storage.file_path(root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


async def personal_library(session: AsyncSession) -> Library:
    """Return the library `make_user` gives an account."""
    await make_user(session)
    return await get_library(session, LibraryType.USER, 1)


def age(root: Path, digest: str, *, hours: int) -> None:
    """Backdate a stored file, as if it had been sitting there."""
    path = storage.file_path(root, digest)
    when = path.stat().st_mtime - hours * 3600
    os.utime(path, (when, when))


DIGEST = "0" * 32
OTHER = "1" * 32


class TestWhatALibraryHolds:
    async def test_it_counts_items_collections_and_tags(
        self, session: AsyncSession, store: Path
    ) -> None:
        library = await personal_library(session)
        await make_item(session, library)
        await make_item(session, library, deleted=True)

        report = await storagestats.collect(session, store)

        (entry,) = report.libraries
        assert entry.items == 2
        assert entry.trashed == 1

    async def test_it_reports_the_library_version(self, session: AsyncSession, store: Path) -> None:
        """The other half of what motivation.md asks an operator view for."""
        library = await personal_library(session)
        library.version = 17
        await session.commit()

        report = await storagestats.collect(session, store)

        assert report.libraries[0].version == 17


class TestNominalAgainstReal:
    async def test_a_shared_file_is_counted_once_on_disk_and_twice_in_libraries(
        self, session: AsyncSession, store: Path
    ) -> None:
        personal = await personal_library(session)
        group = await make_group(session, group_id=100, owner_id=1)
        put_file(store, DIGEST, b"x" * 1000)
        for library in (personal, group):
            await make_item(session, library, item_type="attachment", fields={"md5": DIGEST})

        report = await storagestats.collect(session, store)

        assert report.nominal_bytes == 2000
        assert report.real_bytes == 1000
        assert report.saved_bytes == 1000

    async def test_one_library_pays_the_whole_of_its_own_file(
        self, session: AsyncSession, store: Path
    ) -> None:
        library = await personal_library(session)
        put_file(store, DIGEST, b"x" * 1000)
        await make_item(session, library, item_type="attachment", fields={"md5": DIGEST})

        report = await storagestats.collect(session, store)

        assert report.libraries[0].bytes == 1000

    async def test_the_same_file_attached_twice_in_one_library_is_counted_once(
        self, session: AsyncSession, store: Path
    ) -> None:
        """A library is charged for bytes, not for attachments."""
        library = await personal_library(session)
        put_file(store, DIGEST, b"x" * 1000)
        for _ in range(2):
            await make_item(session, library, item_type="attachment", fields={"md5": DIGEST})

        report = await storagestats.collect(session, store)

        assert report.libraries[0].bytes == 1000
        assert report.libraries[0].files == 1


class TestWhatDoesNotAddUp:
    async def test_a_file_nothing_references_is_an_orphan(
        self, session: AsyncSession, store: Path
    ) -> None:
        await personal_library(session)
        put_file(store, OTHER, b"y" * 500)

        report = await storagestats.collect(session, store)

        assert report.orphan_files == 1
        assert report.orphan_bytes == 500

    async def test_an_attachment_with_no_bytes_is_reported_as_missing(
        self, session: AsyncSession, store: Path
    ) -> None:
        """A restore that lost its files looks exactly like this."""
        library = await personal_library(session)
        await make_item(session, library, item_type="attachment", fields={"md5": DIGEST})

        report = await storagestats.collect(session, store)

        assert report.missing_files == 1
        assert report.libraries[0].missing == 1

    async def test_a_store_that_was_never_written_to_is_not_an_error(
        self, session: AsyncSession, store: Path
    ) -> None:
        """An instance where nobody has uploaded anything has no directory."""
        await personal_library(session)

        report = await storagestats.collect(session, store / "never-used")

        assert report.real_bytes == 0
        assert report.orphan_files == 0


class TestTheLibrariesItNames:
    async def test_a_library_is_named_by_type_and_owner(
        self, session: AsyncSession, store: Path
    ) -> None:
        """The pair that addresses it in the API, so an operator can act on it."""
        library = await personal_library(session)
        library.name = "Ada's library"
        await session.commit()

        report = await storagestats.collect(session, store)

        assert report.libraries[0].type is LibraryType.USER
        assert report.libraries[0].owner_id == 1
        assert report.libraries[0].name == "Ada's library"


class TestPurgingOrphans:
    """Deleting bytes is the riskiest thing in the operator layer.

    Never on a timer, and never without a grace period: a file reaches the disk
    before the item row that refers to it is committed, so an upload in flight
    looks exactly like an orphan for as long as that request takes.
    """

    async def test_an_old_orphan_goes_when_it_is_asked_for(
        self, session: AsyncSession, store: Path
    ) -> None:
        await personal_library(session)
        put_file(store, OTHER, b"y" * 500)
        age(store, OTHER, hours=48)

        files, freed = await storagestats.purge_orphans(session, store, grace=timedelta(hours=24))

        assert (files, freed) == (1, 500)
        assert not storage.file_path(store, OTHER).exists()

    async def test_a_file_that_has_just_arrived_is_left_alone(
        self, session: AsyncSession, store: Path
    ) -> None:
        """This is the upload in flight, and it is the whole reason for a grace."""
        await personal_library(session)
        put_file(store, OTHER, b"y" * 500)

        files, freed = await storagestats.purge_orphans(session, store, grace=timedelta(hours=24))

        assert (files, freed) == (0, 0)
        assert storage.file_path(store, OTHER).exists()

    async def test_a_referenced_file_is_never_touched(
        self, session: AsyncSession, store: Path
    ) -> None:
        library = await personal_library(session)
        put_file(store, DIGEST, b"x" * 1000)
        age(store, DIGEST, hours=4000)
        await make_item(session, library, item_type="attachment", fields={"md5": DIGEST})

        files, _ = await storagestats.purge_orphans(session, store, grace=timedelta(hours=24))

        assert files == 0
        assert storage.file_path(store, DIGEST).exists()

    async def test_a_file_in_another_library_is_not_an_orphan(
        self, session: AsyncSession, store: Path
    ) -> None:
        """The digest is shared; only the union of every library counts."""
        personal = await personal_library(session)
        group = await make_group(session, group_id=100, owner_id=1)
        put_file(store, DIGEST, b"x" * 1000)
        age(store, DIGEST, hours=4000)
        await make_item(session, group, item_type="attachment", fields={"md5": DIGEST})
        assert personal is not None

        files, _ = await storagestats.purge_orphans(session, store, grace=timedelta(hours=24))

        assert files == 0
