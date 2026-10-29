"""Archives remain consistent while PostgreSQL writers are in flight."""

import asyncio
import json
import zipfile
from contextlib import suppress
from pathlib import Path

import pytest
from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Database
from altero.errors import InvalidInputError
from altero.models import Item, ItemField, Library, LibraryType, Setting
from altero.services import transfer, writes
from tests.factories import make_item
from tests.test_concurrency import database as database
from tests.test_concurrency import pytestmark as pytestmark


async def test_an_archive_does_not_mix_two_committed_states(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with database.session_factory() as session:
        library = await session.scalar(select(Library))
        assert library is not None
        item = await make_item(session, library, fields={"title": "old"}, version=0)
        session.add(Setting(library_id=library.id, name="marker", value='"old"', version=0))
        await session.commit()
        item_id, library_id = item.id, library.id

    async def change() -> None:
        async with database.session_factory() as writer:
            library = await writer.get(Library, library_id)
            assert library is not None
            library = await writes.lock_library(writer, library)
            version = await writes.bump_library_version(writer, library)
            await writer.execute(
                update(ItemField).where(ItemField.item_id == item_id).values(value="new")
            )
            await writer.execute(update(Item).where(Item.id == item_id).values(version=version))
            await writer.execute(
                update(Setting)
                .where(Setting.library_id == library_id)
                .values(value='"new"', version=version)
            )
            await writer.commit()

    scalars = AsyncSession.scalars
    writer = None

    async def held(self: AsyncSession, statement, *args, **kwargs):
        nonlocal writer
        rows = await scalars(self, statement, *args, **kwargs)
        if isinstance(statement, Select) and statement.column_descriptions[0].get("expr") is Item:
            writer = asyncio.create_task(change())
            # Without a snapshot lock, the writer commits between table reads.
            # With it, the writer waits until the archive is finished.
            with suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(writer), timeout=2)
        return rows

    monkeypatch.setattr(AsyncSession, "scalars", held)
    async with database.session_factory() as session:
        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "archive.zip",
        )
    assert writer is not None
    await asyncio.wait_for(writer, timeout=10)
    with zipfile.ZipFile(archive) as bundle:
        item = json.loads(bundle.read("items.json"))[0]
        setting = json.loads(bundle.read("settings.json"))[0]
        version = json.loads(bundle.read("manifest.json"))["library"]["version"]
    assert item["fields"][0]["value"] == json.loads(setting["value"])
    assert item["version"] <= version
    assert setting["version"] <= version


async def test_restore_cannot_merge_with_a_writer_that_was_already_in_flight(
    database: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with database.session_factory() as session:
        library = await session.scalar(select(Library))
        assert library is not None
        await make_item(session, library, key="ARCHIVED", fields={"title": "Archived"}, version=0)
        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=tmp_path / "storage",
            destination=tmp_path / "archive.zip",
        )
        await transfer.clear_library(session, library)
        await session.commit()
        library_id = library.id

    reached_empty_check = asyncio.Event()
    is_empty = transfer.is_empty

    async def observed_empty(session: AsyncSession, library: Library) -> bool:
        empty = await is_empty(session, library)
        reached_empty_check.set()
        return empty

    monkeypatch.setattr(transfer, "is_empty", observed_empty)

    async def restore() -> bool:
        async with database.session_factory() as session:
            try:
                await transfer.import_library(
                    session, archive=archive, storage_root=tmp_path / "storage"
                )
                return True
            except InvalidInputError:
                return False

    async with database.session_factory() as writer:
        library = await writer.get(Library, library_id)
        assert library is not None
        library = await writes.lock_library(writer, library)
        version = await writes.bump_library_version(writer, library)
        writer.add(Item(library_id=library_id, key="NEWWRITE", item_type="book", version=version))
        await writer.flush()
        restoring = asyncio.create_task(restore())
        with suppress(TimeoutError):
            await asyncio.wait_for(reached_empty_check.wait(), timeout=2)
        await writer.commit()

    assert await asyncio.wait_for(restoring, timeout=10) is False
    async with database.session_factory() as session:
        assert list(await session.scalars(select(Item.key))) == ["NEWWRITE"]
