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


def _enforce_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Turn on foreign key checking for SQLite, which leaves it off by default.

    Without this a dangling reference is stored silently, and the bug only
    surfaces on a backend that does enforce them.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(connection: Any, _record: Any) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Database:
    """Owns the async engine and hands out sessions."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
        )
        _enforce_sqlite_foreign_keys(self.engine)
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
