"""A download serves the file an upload registered, never the digest an item claims.

Upstream's line (`Zotero_Storage::getDownloadURL`): an attachment's ``md5`` is
metadata any client may write, and the bytes come from `storageFileItems`,
which only an upload writes. Files here are shared by digest across libraries,
so a server that served the claim would hand anybody who knew a digest the
file behind it -- another library's, or a group's they had since left.

What is left of that, as upstream leaves it: an upload authorization naming a
digest and its exact size is answered ``exists`` and given the file.
"""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library, LibraryType
from altero.services import itemwrites, storage, transfer
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import make_api_key, make_item, make_user

ADA = {"Zotero-API-Key": "AdaAdaAdaAdaAdaAdaAdaAda"}
GRACE = {"Zotero-API-Key": "GraceGraceGraceGraceGrac"}

SECRET = b"Grace's unpublished results, which Ada has never seen."
SECRET_MD5 = hashlib.md5(SECRET).hexdigest()


def authorization(md5: str = SECRET_MD5, size: int = len(SECRET)) -> dict[str, str]:
    return {"md5": md5, "filename": "results.txt", "filesize": str(size), "mtime": "1700000000000"}


async def upload(
    client: httpx2.AsyncClient, auth: dict[str, str], prefix: str, key: str, content: bytes
) -> None:
    """The whole three-step upload, as a desktop runs it."""
    form = authorization(hashlib.md5(content).hexdigest(), len(content))
    body = (
        await client.post(
            f"{prefix}/items/{key}/file", headers=auth | {"If-None-Match": "*"}, data=form
        )
    ).json()
    if "exists" in body:
        return
    await client.post(body["url"], content=content)
    registered = await client.post(
        f"{prefix}/items/{key}/file",
        headers=auth | {"If-None-Match": "*"},
        data={"upload": body["uploadKey"]},
    )
    assert registered.status_code == 204


async def attachment(
    client: httpx2.AsyncClient, auth: dict[str, str], prefix: str, **fields: Any
) -> str:
    """A stored-file attachment written through the v3 API, with whatever fields it claims."""
    response = await client.post(
        f"{prefix}/items",
        headers=auth,
        json=[{"itemType": "attachment", "linkMode": "imported_file", "title": "A file", **fields}],
    )
    assert response.status_code == 200, response.text
    return str(response.json()["successful"]["0"]["key"])


@pytest.fixture
async def libraries(session: AsyncSession) -> tuple[Library, Library]:
    """Ada's library and Grace's, Grace's holding a file only she uploaded."""
    for user_id, auth in ((1, ADA), (2, GRACE)):
        await make_user(session, user_id=user_id, username=f"user{user_id}")
        await make_api_key(session, key=auth["Zotero-API-Key"], user_id=user_id)
    await session.commit()
    return (
        await get_library(session, LibraryType.USER, 1),
        await get_library(session, LibraryType.USER, 2),
    )


@pytest.fixture
async def secret(client: httpx2.AsyncClient, libraries: tuple[Library, Library]) -> str:
    key = await attachment(client, GRACE, "/users/2", filename="results.txt")
    await upload(client, GRACE, "/users/2", key, SECRET)
    downloaded = await client.get(f"/users/2/items/{key}/file/content", headers=GRACE)
    assert downloaded.content == SECRET
    return key


class TestAClaimIsNotAFile:
    async def test_naming_somebody_elses_digest_downloads_nothing(
        self, client: httpx2.AsyncClient, secret: str
    ) -> None:
        key = await attachment(client, ADA, "/users/1", md5=SECRET_MD5, mtime=1, filename="x.txt")

        assert (await client.get(f"/users/1/items/{key}", headers=ADA)).json()["data"][
            "md5"
        ] == SECRET_MD5
        assert (await client.get(f"/users/1/items/{key}/file", headers=ADA)).status_code == 404
        assert (
            await client.get(f"/users/1/items/{key}/file/content", headers=ADA)
        ).status_code == 404
        assert (await client.get(f"/users/1/items/{key}/file/view", headers=ADA)).status_code == 404

    async def test_nor_does_changing_ones_own_attachment_to_it(
        self, client: httpx2.AsyncClient, secret: str
    ) -> None:
        """The registered bytes stay what is served, as upstream's link does."""
        mine = b"Ada's own notes."
        key = await attachment(client, ADA, "/users/1")
        await upload(client, ADA, "/users/1", key, mine)
        version = (await client.get(f"/users/1/items/{key}", headers=ADA)).json()["version"]

        changed = await client.patch(
            f"/users/1/items/{key}",
            headers=ADA | {"If-Unmodified-Since-Version": str(version)},
            json={"md5": SECRET_MD5},
        )

        assert changed.status_code == 204
        assert (await client.get(f"/users/1/items/{key}/file/content", headers=ADA)).content == mine

    async def test_nor_does_an_export_carry_it(
        self,
        client: httpx2.AsyncClient,
        session: AsyncSession,
        settings: Settings,
        secret: str,
        tmp_path: Path,
    ) -> None:
        await attachment(client, ADA, "/users/1", md5=SECRET_MD5, mtime=1, filename="x.txt")

        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=settings.storage_path,
            destination=tmp_path / "ada.zip",
        )

        with zipfile.ZipFile(archive) as bundle:
            assert f"files/{SECRET_MD5}" not in bundle.namelist()


class TestTheUploadsShortcut:
    async def test_a_digest_without_its_size_is_asked_for_the_bytes(
        self, client: httpx2.AsyncClient, secret: str
    ) -> None:
        key = await attachment(client, ADA, "/users/1")

        response = await client.post(
            f"/users/1/items/{key}/file",
            headers=ADA | {"If-None-Match": "*"},
            data=authorization(size=len(SECRET) + 1),
        )

        assert response.status_code == 200
        assert "exists" not in response.json()
        assert (
            await client.get(f"/users/1/items/{key}/file/content", headers=ADA)
        ).status_code == 404

    async def test_the_digest_and_its_size_are_taken_as_the_file(
        self, client: httpx2.AsyncClient, secret: str
    ) -> None:
        """Upstream's own rule, and the reason a second copy is never sent."""
        key = await attachment(client, ADA, "/users/1")

        response = await client.post(
            f"/users/1/items/{key}/file", headers=ADA | {"If-None-Match": "*"}, data=authorization()
        )

        assert response.json() == {"exists": 1}
        assert (
            await client.get(f"/users/1/items/{key}/file/content", headers=ADA)
        ).content == SECRET


class TestWhatCarriesARegistration:
    async def test_a_copy_reads_the_file_its_original_does(
        self, client: httpx2.AsyncClient, session: AsyncSession, settings: Settings, secret: str
    ) -> None:
        grace = await get_library(session, LibraryType.USER, 2)
        original = await session.scalar(select(Item).where(Item.key == secret))
        assert original is not None

        copy = await itemwrites.copy_item(session, grace, original, grace.version + 1)
        await session.commit()

        assert copy.registered_md5 == SECRET_MD5
        path, _ = await storage.stored_file(copy, settings.storage_path)
        assert path.read_bytes() == SECRET

    async def test_a_restore_registers_only_what_the_archive_carries(
        self,
        client: httpx2.AsyncClient,
        session: AsyncSession,
        settings: Settings,
        secret: str,
        tmp_path: Path,
    ) -> None:
        """An archive naming a digest it does not bring along is a claim like any other."""
        mine = b"Ada's own notes."
        carried = await attachment(client, ADA, "/users/1")
        await upload(client, ADA, "/users/1", carried, mine)
        claimed = await attachment(
            client, ADA, "/users/1", md5=SECRET_MD5, mtime=1, filename="x.txt"
        )
        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=settings.storage_path,
            destination=tmp_path / "ada.zip",
        )
        _forge(archive, claimed)

        await transfer.import_library(
            session, archive=archive, storage_root=settings.storage_path, replace=True
        )

        restored = {
            item.key: item.registered_md5
            for item in await session.scalars(select(Item).where(Item.key.in_([carried, claimed])))
        }
        assert restored == {carried: hashlib.md5(mine).hexdigest(), claimed: None}

    async def test_an_older_archive_registers_the_claim_it_carries(
        self,
        session: AsyncSession,
        settings: Settings,
        libraries: tuple[Library, Library],
        tmp_path: Path,
    ) -> None:
        """Archives from before the record, and `zoteroimport`'s, name the file by its claim."""
        ada, _ = libraries
        await make_item(
            session,
            ada,
            key="CCCC2345",
            item_type="attachment",
            fields={"linkMode": "imported_file", "md5": SECRET_MD5, "filename": "r.txt"},
        )
        storage.store_file(settings.storage_path, SECRET_MD5, SECRET)
        archive = await transfer.export_library(
            session,
            library_type=LibraryType.USER,
            owner_id=1,
            storage_root=settings.storage_path,
            destination=tmp_path / "old.zip",
        )
        _forge(archive, None)

        await transfer.import_library(
            session, archive=archive, storage_root=settings.storage_path, replace=True
        )

        item = await session.scalar(select(Item).where(Item.key == "CCCC2345"))
        assert item is not None
        assert item.registered_md5 == SECRET_MD5


def _forge(archive: Path, claimed: str | None) -> None:
    """Rewrite ``archive``'s items: ``claimed`` registers the secret it does not carry,
    and with ``None``, every record loses `registeredMd5`, as an older archive has none."""
    with zipfile.ZipFile(archive) as bundle:
        contents = {name: bundle.read(name) for name in bundle.namelist()}
    items = json.loads(contents["items.json"])
    for record in items:
        if claimed is None:
            record.pop("registeredMd5", None)
        elif record["key"] == claimed:
            record["registeredMd5"] = SECRET_MD5
    contents["items.json"] = json.dumps(items).encode()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in contents.items():
            bundle.writestr(name, data)


def test_upgrading_registers_the_files_attachments_already_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing that downloads before the migration stops downloading after it."""
    import sqlite3

    from alembic import command
    from alembic.config import Config

    from altero.settings import get_settings

    path = tmp_path / "upgraded.sqlite"
    monkeypatch.setenv("ALTERO_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent.parent / "migrations")
    )
    rows = {
        1: ("attachment", {"linkMode": "imported_file", "md5": SECRET_MD5.upper()}),
        2: ("attachment", {"linkMode": "imported_url", "md5": "f" * 32}),
        3: ("attachment", {"linkMode": "linked_url", "md5": "e" * 32}),
        4: ("attachment", {"linkMode": "imported_file", "md5": "../../etc/passwd"}),
        5: ("attachment", {"linkMode": "imported_file"}),
        6: ("book", {"md5": "d" * 32}),
    }
    try:
        command.upgrade(config, "a3f1c6d2e8b4")
        with sqlite3.connect(path) as connection:
            for item_id, (item_type, fields) in rows.items():
                connection.execute(
                    "INSERT INTO items (id, library_id, key, version, item_type, deleted, "
                    "in_publications, sort_title, sort_creator, sort_date, date_added, "
                    "date_modified, server_date_modified) VALUES "
                    "(?, 1, ?, 1, ?, 0, 0, '', '', '', '2026-01-01', '2026-01-01', '2026-01-01')",
                    (item_id, f"KEY{item_id}2345"[:8], item_type),
                )
                for name, value in fields.items():
                    connection.execute(
                        "INSERT INTO item_fields (item_id, field, value) VALUES (?, ?, ?)",
                        (item_id, name, value),
                    )
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    with sqlite3.connect(path) as connection:
        registered = dict(connection.execute("SELECT id, registered_md5 FROM items").fetchall())
    assert registered == {1: SECRET_MD5, 2: "f" * 32, 3: None, 4: None, 5: None, 6: None}
