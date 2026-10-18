"""The engine's own settings: what every SQLite connection is opened with."""

from pathlib import Path

from sqlalchemy import QueuePool, text

from altero.db import Database
from altero.models import LibraryType
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import make_item, make_user


async def _item_statistics(database: Database) -> int | None:
    """Return how many items SQLite's planner believes there are, if it has a figure."""
    async with database.engine.connect() as connection:
        exists = await connection.scalar(
            text("SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_stat1'")
        )
        if not exists:
            return None
        row = await connection.scalar(
            text("SELECT stat FROM sqlite_stat1 WHERE idx = 'ix_items_library_version'")
        )
    return int(row.split()[0]) if row else None


async def _add_items(database: Database, count: int) -> None:
    async with database.session_factory() as session:
        library = await get_library(session, LibraryType.USER, 1)
        for _ in range(count):
            await make_item(session, library)


class TestPlannerStatistics:
    """SQLite plans without statistics until somebody runs ANALYZE, and nobody did.

    A library of 30k items then took 25 s for a tag listing that takes a fraction
    of a second once the planner knows how many rows each index holds.
    """

    async def test_a_connection_gives_an_unanalysed_database_statistics(
        self, tmp_path: Path
    ) -> None:
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'stats.sqlite'}")
        first = Database(settings)
        await first.create_all()
        async with first.session_factory() as session:
            await make_user(session, user_id=1)
        await _add_items(first, 20)
        await first.dispose()

        second = Database(settings)
        try:
            assert await _item_statistics(second) == 20
        finally:
            await second.dispose()

    async def test_optimizing_catches_up_with_a_library_that_grew(self, tmp_path: Path) -> None:
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'grown.sqlite'}")
        database = Database(settings)
        try:
            await database.create_all()
            async with database.session_factory() as session:
                await make_user(session, user_id=1)
            await _add_items(database, 5)
            await database.optimize()
            assert await _item_statistics(database) == 5

            await _add_items(database, 200)
            await database.optimize()

            assert await _item_statistics(database) == 205
        finally:
            await database.dispose()


class TestConnectionSettings:
    async def test_a_sqlite_connection_may_use_memory(self, tmp_path: Path) -> None:
        """A 2 MB cache and sorting on disk are SQLite's defaults, sized for a phone."""
        database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))
        async with database.engine.connect() as connection:
            cache = await connection.scalar(text("PRAGMA cache_size"))
            temp_store = await connection.scalar(text("PRAGMA temp_store"))
            mmap = await connection.scalar(text("PRAGMA mmap_size"))
        await database.dispose()

        assert (cache, temp_store, mmap) == (-16384, 2, 268435456)

    def test_the_pool_takes_its_size_from_the_settings(self, tmp_path: Path) -> None:
        database = Database(
            Settings(
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
                database_pool_size=3,
                database_max_overflow=4,
            )
        )
        pool = database.engine.sync_engine.pool

        assert isinstance(pool, QueuePool)
        assert (pool.size(), pool._max_overflow) == (3, 4)

    def test_a_postgresql_pool_is_sized_the_same_way(self) -> None:
        database = Database(
            Settings(
                database_url="postgresql+asyncpg://altero:altero@localhost:1/altero",
                database_pool_size=8,
            )
        )

        pool = database.engine.sync_engine.pool

        assert isinstance(pool, QueuePool)
        assert pool.size() == 8

    def test_an_in_memory_database_keeps_its_single_connection(self) -> None:
        Database(Settings(database_url="sqlite+aiosqlite:///:memory:"))
