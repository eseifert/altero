"""Exporting a library and restoring it somewhere else.

The assertion that matters is equality: everything a client can observe has to
survive the round trip, versions included. A restore that renumbers versions
looks successful and locks out every client that had synced against the
original -- see "After recreating the database" in docs/administration.md,
which exists because that failure was seen against a real client.

So rather than checking a handful of fields, these tests dump both libraries in
full and compare. A table added to the schema and forgotten here shows up as a
difference rather than as silence.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Database
from altero.errors import InvalidInputError, NotFoundError
from altero.models import (
    Collection,
    CollectionItem,
    CollectionRelation,
    DeletedObject,
    FullText,
    Item,
    ItemTag,
    Library,
    LibraryType,
    SavedSearch,
    Setting,
    Tag,
)
from altero.services import storage, transfer
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import (
    make_collection,
    make_item,
    make_search,
    make_user,
    tag_item,
)

SNAPSHOT = b"<html><body>The Brutalist Report</body></html>"


async def snapshot(session: AsyncSession, library: Library) -> dict[str, Any]:
    """Return everything about a library that a client could observe."""
    items = list(
        await session.scalars(select(Item).where(Item.library_id == library.id).order_by(Item.key))
    )
    by_id = {item.id: item.key for item in items}

    collections = list(
        await session.scalars(
            select(Collection).where(Collection.library_id == library.id).order_by(Collection.key)
        )
    )
    collection_ids = {collection.id: collection.key for collection in collections}

    searches = list(
        await session.scalars(
            select(SavedSearch)
            .where(SavedSearch.library_id == library.id)
            .order_by(SavedSearch.key)
        )
    )
    tags = list(
        await session.scalars(select(Tag).where(Tag.library_id == library.id).order_by(Tag.name))
    )
    tag_ids = {tag.id: tag.name for tag in tags}

    memberships = list(
        await session.scalars(
            select(CollectionItem).where(CollectionItem.collection_id.in_(collection_ids))
        )
    )
    item_tags = list(await session.scalars(select(ItemTag).where(ItemTag.tag_id.in_(tag_ids))))

    return {
        "library": {"version": library.version, "name": library.name},
        "items": [
            {
                "key": item.key,
                "version": item.version,
                "itemType": item.item_type,
                "parent": by_id.get(item.parent_id) if item.parent_id else None,
                "deleted": item.deleted,
                "inPublications": item.in_publications,
                "sort": [item.sort_title, item.sort_creator, item.sort_date],
                "dateAdded": item.date_added.isoformat(),
                "dateModified": item.date_modified.isoformat(),
                "serverDateModified": item.server_date_modified.isoformat(),
                "fields": sorted((f.field, f.value) for f in item.fields),
                "creators": [
                    (c.position, c.creator_type, c.first_name, c.last_name, c.name)
                    for c in sorted(item.creators, key=lambda c: c.position)
                ],
                "relations": sorted((r.predicate, r.object) for r in item.relations),
            }
            for item in items
        ],
        "collections": [
            {
                "key": collection.key,
                "version": collection.version,
                "name": collection.name,
                "parent": collection_ids.get(collection.parent_id)
                if collection.parent_id
                else None,
                "deleted": collection.deleted,
                "relations": sorted((r.predicate, r.object) for r in collection.relations),
            }
            for collection in collections
        ],
        "membership": sorted(
            (collection_ids[m.collection_id], by_id[m.item_id]) for m in memberships
        ),
        "searches": [
            {
                "key": search.key,
                "version": search.version,
                "name": search.name,
                "deleted": search.deleted,
                "conditions": [
                    (c.position, c.condition, c.operator, c.value)
                    for c in sorted(search.conditions, key=lambda c: c.position)
                ],
            }
            for search in searches
        ],
        "tags": [
            {"key": tag.key, "name": tag.name, "type": tag.type, "version": tag.version}
            for tag in tags
        ],
        "itemTags": sorted((tag_ids[it.tag_id], by_id[it.item_id]) for it in item_tags),
        "settings": sorted(
            (setting.name, setting.value, setting.version)
            for setting in await session.scalars(
                select(Setting).where(Setting.library_id == library.id)
            )
        ),
        "fulltext": sorted(
            (by_id[text.item_id], text.content, text.version, text.indexed_chars, text.total_chars)
            for text in await session.scalars(
                select(FullText).where(FullText.library_id == library.id)
            )
        ),
        "deleted": sorted(
            (record.object_type, record.key, record.version)
            for record in await session.scalars(
                select(DeletedObject).where(DeletedObject.library_id == library.id)
            )
        ),
    }


async def populate(session: AsyncSession, library: Library, storage_root: Path) -> None:
    """Fill a library with one of everything that has to survive a round trip."""
    library.version = 37
    parent = await make_item(
        session,
        library,
        key="Z2JFGHNV",
        item_type="webpage",
        version=11,
        in_publications=True,
        fields={"title": "The Brutalist Report", "url": "https://brutalist.report/"},
        creators=[("author", "Erich", "Seifert")],
    )
    attachment = await make_item(
        session,
        library,
        key="BG92XXQJ",
        item_type="attachment",
        version=12,
        parent=parent,
        fields={
            "title": "Snapshot",
            "linkMode": "imported_url",
            "contentType": "text/html",
            "filename": "brutalist.report.html",
            "md5": storage.file_digest(SNAPSHOT),
        },
    )
    trashed = await make_item(session, library, key="TRASHED1", version=13, deleted=True)

    collection = await make_collection(
        session, library, key="COLLECT1", name="Reading", version=14, items=[parent]
    )
    collection.relations = [
        CollectionRelation(
            predicate="owl:sameAs", object="http://zotero.org/users/9/collections/AAAA2345"
        )
    ]
    await make_collection(
        session,
        library,
        key="COLLECT2",
        name="Nested",
        version=15,
        parent=collection,
        deleted=True,
    )
    await make_search(
        session,
        library,
        key="SEARCH01",
        name="Recent",
        version=16,
        conditions=[("title", "contains", "Brutalist")],
        deleted=True,
    )
    await tag_item(session, library, parent, "news", tag_type=0, version=17)
    await tag_item(session, library, trashed, "automatic", tag_type=1, version=18)

    session.add(
        Setting(library_id=library.id, name="tagColors", value='[{"name":"x"}]', version=19)
    )
    session.add(
        FullText(
            item_id=attachment.id,
            library_id=library.id,
            content="The Brutalist Report",
            version=20,
            indexed_chars=20,
            total_chars=20,
        )
    )
    session.add(
        DeletedObject(library_id=library.id, object_type="item", key="GONEGONE", version=21)
    )
    await session.commit()

    path = storage.file_path(storage_root, storage.file_digest(SNAPSHOT))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(SNAPSHOT)


@pytest.fixture
async def target(tmp_path: Path) -> AsyncIterator[tuple[AsyncSession, Path]]:
    """A second, empty instance to restore into."""
    database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'target.sqlite'}"))
    await database.create_all()
    async with database.session_factory() as session:
        yield session, tmp_path / "target-storage"
    await database.dispose()


class TestRoundTrip:
    async def test_a_restored_library_is_the_one_that_was_exported(
        self,
        session: AsyncSession,
        tmp_path: Path,
        target: tuple[AsyncSession, Path],
    ) -> None:
        source_storage = tmp_path / "source-storage"
        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, source_storage)
        before = await snapshot(session, library)

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=source_storage,
            destination=tmp_path / "library.zip",
        )

        target_session, target_storage = target
        await make_user(target_session, user_id=1, username="octocat")
        restored = await transfer.import_library(
            target_session, archive=archive, storage_root=target_storage
        )

        assert await snapshot(target_session, restored) == before

    async def test_the_attachment_bytes_come_with_it(
        self,
        session: AsyncSession,
        tmp_path: Path,
        target: tuple[AsyncSession, Path],
    ) -> None:
        # A restore that carries the metadata but not the files leaves every
        # attachment pointing at nothing.
        source_storage = tmp_path / "source-storage"
        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, source_storage)

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=source_storage,
            destination=tmp_path / "library.zip",
        )

        target_session, target_storage = target
        await make_user(target_session, user_id=1, username="octocat")
        await transfer.import_library(target_session, archive=archive, storage_root=target_storage)

        stored = storage.file_path(target_storage, storage.file_digest(SNAPSHOT))
        assert stored.read_bytes() == SNAPSHOT

    async def test_the_library_version_survives(
        self,
        session: AsyncSession,
        tmp_path: Path,
        target: tuple[AsyncSession, Path],
    ) -> None:
        """The whole reason this has to be exact.

        A library restored at version 0 while its clients remember 37 cannot be
        synced or reset out of; the client refuses to move its own version
        backwards in either direction.
        """
        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, tmp_path / "source-storage")

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "source-storage",
            destination=tmp_path / "library.zip",
        )

        target_session, target_storage = target
        await make_user(target_session, user_id=1, username="octocat")
        restored = await transfer.import_library(
            target_session, archive=archive, storage_root=target_storage
        )

        assert restored.version == 37


class TestRefusals:
    async def test_exporting_a_library_that_is_not_there_is_rejected(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        with pytest.raises(NotFoundError):
            await transfer.export_library(
                session,
                library_type=LibraryType.USER,
                owner_id=99,
                storage_root=tmp_path,
                destination=tmp_path / "x.zip",
            )

    async def test_restoring_over_a_library_with_objects_is_refused(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        # Merging two libraries is not what a restore does, and doing it by
        # accident would be unrecoverable.
        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, tmp_path / "storage")

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )

        with pytest.raises(InvalidInputError, match="not empty"):
            await transfer.import_library(
                session, archive=archive, storage_root=tmp_path / "storage"
            )

    async def test_replacing_is_allowed_when_asked_for(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, tmp_path / "storage")
        before = await snapshot(session, library)

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )
        restored = await transfer.import_library(
            session, archive=archive, storage_root=tmp_path / "storage", replace=True
        )

        assert await snapshot(session, restored) == before

    async def test_restoring_into_a_missing_library_is_rejected(
        self, tmp_path: Path, session: AsyncSession, target: tuple[AsyncSession, Path]
    ) -> None:
        # Accounts are not in the export -- it carries a library, not the user
        # who owns it -- so the owner has to exist first.
        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, tmp_path / "storage")
        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )

        target_session, target_storage = target

        with pytest.raises(NotFoundError):
            await transfer.import_library(
                target_session, archive=archive, storage_root=target_storage
            )


class TestArchive:
    async def test_the_manifest_says_what_produced_it(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        # A backup nobody can identify later is a backup nobody trusts.
        import json
        import zipfile

        await make_user(session, user_id=1, username="octocat")
        library = await get_library(session, LibraryType.USER, 1)
        await populate(session, library, tmp_path / "storage")

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )

        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))

        assert manifest["format"] == transfer.FORMAT_VERSION
        assert manifest["library"] == {"type": "user", "id": 1, "version": 37}
        assert manifest["counts"]["items"] == 3
        assert manifest["counts"]["files"] == 1

    async def test_an_archive_from_the_future_is_refused(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        import json
        import zipfile

        archive = tmp_path / "future.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("manifest.json", json.dumps({"format": transfer.FORMAT_VERSION + 1}))

        with pytest.raises(InvalidInputError, match="format"):
            await transfer.import_library(session, archive=archive, storage_root=tmp_path)

    async def test_something_that_is_not_a_zip_is_refused_as_such(self, tmp_path: Path) -> None:
        """A readable refusal rather than a traceback: the browser can upload
        whatever a file picker gave it."""
        archive = tmp_path / "holiday.jpg"
        archive.write_bytes(b"\xff\xd8\xff\xe0 not a zip")

        with pytest.raises(InvalidInputError, match="not an altero library archive"):
            transfer.read_manifest(archive)

    async def test_a_file_named_anything_but_a_digest_is_refused(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """A stored file's name is joined onto the file store's root, so an
        archive that names one `../../…` would write outside it. Refused
        before a single row is written, not while the files are unpacked."""
        import json
        import zipfile

        await make_user(session, user_id=1, username="octocat")
        archive = tmp_path / "hostile.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": transfer.FORMAT_VERSION,
                        "library": {"type": "user", "id": 1, "version": 1},
                    }
                ),
            )
            bundle.writestr("files/../../../../etc/altero-was-here", b"owned")

        with pytest.raises(InvalidInputError, match="impossible name"):
            await transfer.import_library(
                session, archive=archive, storage_root=tmp_path / "storage"
            )

        assert not (tmp_path / "storage").exists()


class TestRestoringIntoAChosenLibrary:
    """``into`` is what the browser restores through.

    There the target is decided by who is signed in, so the library named in
    the manifest must not be the one that gets written to -- otherwise an
    uploaded file could name somebody else's library and be restored over it.
    """

    async def test_the_contents_land_in_the_library_the_caller_chose(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        await make_user(session, user_id=1, username="octocat")
        await make_user(session, user_id=2, username="grace", display_name="Grace")
        source = await get_library(session, LibraryType.USER, 1)
        await populate(session, source, tmp_path / "storage")
        expected = await snapshot(session, source)

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )
        target = await get_library(session, LibraryType.USER, 2)
        restored = await transfer.import_library(
            session, archive=archive, storage_root=tmp_path / "storage", into=target
        )

        assert restored.id == target.id
        # Everything the archive carried, at the versions it carried them. The
        # name is the one thing that stays the target library's own, and has a
        # test of its own below.
        actual = await snapshot(session, restored)
        assert actual["library"]["version"] == expected["library"]["version"]
        assert {name: rows for name, rows in actual.items() if name != "library"} == {
            name: rows for name, rows in expected.items() if name != "library"
        }

    async def test_the_library_named_in_the_archive_is_left_alone(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        await make_user(session, user_id=1, username="octocat")
        await make_user(session, user_id=2, username="grace", display_name="Grace")
        source = await get_library(session, LibraryType.USER, 1)
        await populate(session, source, tmp_path / "storage")
        before = await snapshot(session, source)

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )
        target = await get_library(session, LibraryType.USER, 2)
        await transfer.import_library(
            session, archive=archive, storage_root=tmp_path / "storage", into=target
        )

        assert await snapshot(session, source) == before

    async def test_the_chosen_library_keeps_its_own_name(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """A name belongs to the library, not to what is in it -- and a group's
        also lives on its `Group` row, which no archive carries."""
        await make_user(session, user_id=1, username="octocat")
        await make_user(session, user_id=2, username="grace", display_name="Grace")
        source = await get_library(session, LibraryType.USER, 1)
        source.name = "Mona Lisa"
        await populate(session, source, tmp_path / "storage")

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "library.zip",
        )
        target = await get_library(session, LibraryType.USER, 2)
        restored = await transfer.import_library(
            session, archive=archive, storage_root=tmp_path / "storage", into=target
        )

        assert restored.name == "Grace"
