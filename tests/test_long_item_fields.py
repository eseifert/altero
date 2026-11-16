"""Long bibliographic fields must survive both migration and ordinary writes."""

import asyncio
import os
import random
from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from altero.app import create_app
from altero.db import Base, Database
from altero.models import Item, LibraryType
from altero.services import transfer
from altero.services.auth import get_library
from altero.services.zoteroimport import fetch_archive
from altero.settings import Settings, get_settings
from tests.factories import make_api_key, make_item, make_user
from tests.test_zotero_import import api, seed
from tests.test_zotero_import import remote as remote
from tests.test_zotero_import import source as source
from tests.test_zotero_import import zotero as zotero

POSTGRES_URL = os.environ.get("ALTERO_TEST_POSTGRES_URL")
BACKENDS = [
    "sqlite",
    pytest.param(
        "postgresql",
        marks=pytest.mark.skipif(not POSTGRES_URL, reason="ALTERO_TEST_POSTGRES_URL is not set"),
    ),
]


@pytest.fixture(params=BACKENDS)
def database_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    if request.param == "sqlite":
        return f"sqlite+aiosqlite:///{tmp_path / 'target.sqlite'}"
    assert POSTGRES_URL
    return POSTGRES_URL


@pytest.fixture(params=["fresh", "upgraded"])
async def target(
    request: pytest.FixtureRequest,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Database]:
    database = Database(Settings(database_url=database_url, storage_path=tmp_path / "target-store"))
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        # create_all does not know Alembic's version table from an earlier test.
        await connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    monkeypatch.setenv("ALTERO_DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        if request.param == "upgraded":
            await asyncio.to_thread(command.upgrade, config, "79be412c6a05")
        else:
            await database.create_all()
        async with database.session_factory() as session:
            await make_user(session)
            await make_api_key(session)
            library = await get_library(session, LibraryType.USER, 1)
            await make_item(session, library, key="EXIST234", fields={"title": "Existing"})
            before = (library.version, await session.scalar(select(Item.sort_title)))
        if request.param == "upgraded":
            # As in deployment, close application connections before migrating;
            # asyncpg's prepared statements retain the old column types.
            await database.engine.dispose()
            await asyncio.to_thread(command.upgrade, config, "head")
            await asyncio.to_thread(command.check, config)
            async with database.session_factory() as session:
                library = await get_library(session, LibraryType.USER, 1)
                assert (library.version, await session.scalar(select(Item.sort_title))) == before
                item = await session.scalar(select(Item))
                assert item is not None
                assert item.key == "EXIST234"
                assert item.version == 1
                assert item.field_values() == {"title": "Existing"}
        yield database
    finally:
        get_settings.cache_clear()
        await database.dispose()


async def test_migration_and_writes_preserve_long_titles_and_dates(
    target: Database,
    database_url: str,
    remote: httpx2.AsyncClient,
    zotero: httpx2.AsyncClient,
    tmp_path: Path,
) -> None:
    # Issue #73: a signed CDN URL was used as a snapshot's title. Upstream's
    # Item.inc.php allows 65,535 bytes per item-data value, including dates.
    # An incompressible larger title also catches PostgreSQL's B-tree entry
    # limit: changing VARCHAR to TEXT while keeping that index is insufficient.
    signed_url = (
        "https://cdn.example.org/download?signature=" + random.Random(73).randbytes(1130).hex()
    )
    large_title = "漢字" + random.Random(74).randbytes(5000).hex()
    date = "2026, revised after publication; " + "additional date information " * 5
    values = [("URLS2345", signed_url), ("HUGE2345", large_title)]
    seeded = await seed(
        zotero,
        [
            {"itemType": "webpage", "key": key, "title": title, "date": date}
            for key, title in values
        ],
    )
    assert not seeded.json()["failed"], seeded.text
    archive = tmp_path / "migration.zip"
    await fetch_archive(api(remote), destination=archive, target_user_id=1)
    async with target.session_factory() as session:
        library = await transfer.import_library(
            session, archive=archive, storage_root=tmp_path / "target-store", replace=True
        )
        assert library.owner_id == 1
        stored = list(await session.scalars(select(Item).order_by(Item.key)))
        assert [(item.key, item.sort_title) for item in stored] == sorted(values)
        assert all(item.sort_date == date for item in stored)
        assert all(item.field_values()["title"] == item.sort_title for item in stored)

    application = create_app(
        Settings(database_url=database_url, storage_path=tmp_path / "target-store")
    )
    transport = httpx2.ASGITransport(app=application)
    try:
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Give the smaller title the later key so truncation would reverse
            # their order. Both titles differ only beyond the former limit.
            prefix = signed_url + " tail "
            response = await client.post(
                "/users/1/items",
                headers={"Zotero-API-Key": "P9NiFoyLeZu2bZNvvuQPDWsd"},
                json=[
                    {"itemType": "webpage", "key": key, "title": prefix + suffix, "date": date}
                    for key, suffix in [("AAAA2345", "z"), ("ZZZZ2345", "a")]
                ],
            )
            assert response.status_code == 200, response.text
            assert not response.json()["failed"], response.text
            response = await client.get(
                "/users/1/items",
                headers={"Zotero-API-Key": "P9NiFoyLeZu2bZNvvuQPDWsd"},
                params={"sort": "title", "direction": "asc", "q": "tail"},
            )
            assert response.status_code == 200, response.text
            assert [item["key"] for item in response.json()] == ["ZZZZ2345", "AAAA2345"]
            assert [item["data"]["title"] for item in response.json()] == [
                prefix + "a",
                prefix + "z",
            ]
            assert all(item["data"]["date"] == date for item in response.json())
    finally:
        await application.state.database.dispose()
