"""Renaming a store an earlier altero wrote, once, when the server starts.

Before, a snapshot ZIP was stored under the digest of the file inside it and a
restored file under whatever digest its archive gave it. After, every file is
named by the digest of its own bytes, and an attachment whose file is a ZIP
around another says so.
"""

import hashlib
import io
import zipfile
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library, LibraryType
from altero.services import storage, storelayout
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import make_api_key, make_item, make_user

AUTH = {"Zotero-API-Key": "AdaAdaAdaAdaAdaAdaAdaAda"}

PAGE = b"<html>a snapshot</html>"
PAGE_MD5 = hashlib.md5(PAGE).hexdigest()
PAPER = b"%PDF-1.7 a paper"
PAPER_MD5 = hashlib.md5(PAPER).hexdigest()
#: A file a zotero.org library kept under a digest that is not its own.
MISFILED = b"the bytes zotero.org served"
CLAIMED = "c" * 32


def _snapshot() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("page.html", PAGE)
    return buffer.getvalue()


SNAPSHOT = _snapshot()
SNAPSHOT_MD5 = hashlib.md5(SNAPSHOT).hexdigest()


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=AUTH["Zotero-API-Key"], user_id=1)
    return await get_library(session, LibraryType.USER, 1)


@pytest.fixture
async def old_store(session: AsyncSession, settings: Settings, library: Library) -> Path:
    """A store as an earlier altero left it, with the rows the migration gave it."""
    root = settings.storage_path
    for key, link_mode, digest, body in (
        ("SNAP2345", "imported_url", PAGE_MD5, SNAPSHOT),
        ("PDFF2345", "imported_file", PAPER_MD5, PAPER),
        ("MISS2345", "imported_file", CLAIMED, MISFILED),
    ):
        await make_item(
            session,
            library,
            key=key,
            item_type="attachment",
            fields={"linkMode": link_mode, "md5": digest, "mtime": "1", "filename": "f"},
        )
        storage.store_file(root, digest, body)
    return root


async def registered(session: AsyncSession) -> dict[str, tuple[str | None, bool]]:
    session.expire_all()
    return {
        item.key: (item.registered_md5, item.registered_zip)
        for item in await session.scalars(select(Item))
    }


async def test_each_file_is_renamed_to_its_own_digest(
    session: AsyncSession, old_store: Path
) -> None:
    moved = await storelayout.ensure_current(session, old_store)

    assert moved == 2
    assert await registered(session) == {
        "SNAP2345": (SNAPSHOT_MD5, True),
        "PDFF2345": (PAPER_MD5, False),
        "MISS2345": (hashlib.md5(MISFILED).hexdigest(), False),
    }
    assert storage.file_path(old_store, SNAPSHOT_MD5).read_bytes() == SNAPSHOT
    assert not storage.file_path(old_store, PAGE_MD5).exists()
    assert not storage.file_path(old_store, CLAIMED).exists()
    assert storage.file_path(old_store, PAPER_MD5).read_bytes() == PAPER


async def test_a_snapshot_still_downloads_as_one(
    client: httpx2.AsyncClient, session: AsyncSession, old_store: Path
) -> None:
    await storelayout.ensure_current(session, old_store)

    redirect = await client.get("/users/1/items/SNAP2345/file", headers=AUTH)

    assert redirect.headers["Zotero-File-Compressed"] == "Yes"
    assert redirect.headers["Zotero-File-MD5"] == PAGE_MD5
    assert (await client.get(redirect.headers["Location"])).content == SNAPSHOT


async def test_it_is_done_once(session: AsyncSession, old_store: Path) -> None:
    await storelayout.ensure_current(session, old_store)
    storage.store_file(old_store, "d" * 32, b"left there afterwards")

    assert await storelayout.ensure_current(session, old_store) == 0
    assert (old_store / storelayout.MARKER).read_text().strip() == storelayout.LAYOUT


async def test_cut_off_part_way_it_finishes_next_time(
    session: AsyncSession, old_store: Path
) -> None:
    """Linked but not yet recorded: the old name still serves until it is."""
    storelayout._content_name(old_store, PAGE_MD5)

    assert storage.file_path(old_store, PAGE_MD5).exists()
    assert await storelayout.ensure_current(session, old_store) == 2
    assert (await registered(session))["SNAP2345"] == (SNAPSHOT_MD5, True)
    assert not storage.file_path(old_store, PAGE_MD5).exists()


async def test_a_new_store_is_simply_marked(session: AsyncSession, tmp_path: Path) -> None:
    root = tmp_path / "fresh"

    assert await storelayout.ensure_current(session, root) == 0
    assert (root / storelayout.MARKER).is_file()


def test_the_marker_is_nothing_a_sweep_removes() -> None:
    """Not a digest, and not what an abandoned write is called."""
    for name in (storelayout.MARKER, storelayout.LOCK):
        assert not storage.is_file_digest(name)
        assert not name.startswith(storage.STAGING_PREFIX)
