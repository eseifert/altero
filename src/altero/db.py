"""Database engine, session factory and ORM base class."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, event, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from altero.settings import Settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


class Timestamped:
    """The three timestamps the dataserver keeps on every syncable object.

    ``date_added`` and ``date_modified`` are supplied by the client and round-trip
    through the API. ``server_date_modified`` is set by the server on every write
    and is what the ``serverDateModified`` sort orders by, so a client cannot
    reorder results by backdating its own timestamps.
    """

    date_added: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    date_modified: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    server_date_modified: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


def _configure_sqlite(engine: AsyncEngine) -> None:
    """Apply the settings SQLite needs to behave under concurrent writes.

    Three things are wrong with SQLite's defaults here:

    - Foreign keys are not enforced, so a dangling reference is stored silently
      and only surfaces on a backend that does check.
    - The rollback journal blocks readers while a write is in progress. WAL lets
      them run alongside it.
    What is deliberately not done here is beginning every transaction with
    ``BEGIN IMMEDIATE``. It would close the remaining hole — a transaction that
    reads and then writes can fail outright when it upgrades its lock, which
    ``busy_timeout`` does not cover — but it takes the write lock for read-only
    transactions too, so a single long read blocks every writer. That is a worse
    trade than the hole it fills. A deployment serving more than one client at a
    time should use PostgreSQL, where the row lock in the write path does the
    job properly.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(connection: Any, _record: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # An in-memory database has no journal to switch.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


class Database:
    """Owns the async engine and hands out sessions."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
        )
        _configure_sqlite(self.engine)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session, rolling back if the caller raises."""
        async with self.session_factory() as session:
            yield session

    async def create_all(self) -> None:
        """Create every table. Intended for tests; production uses Alembic."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
