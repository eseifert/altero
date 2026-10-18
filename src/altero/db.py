"""Database engine, session factory and ORM base class."""

import logging
import sqlite3
from collections.abc import AsyncIterator, Collection, Iterator, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import BindParameter, DateTime, Integer, bindparam, event, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from altero.settings import Settings

logger = logging.getLogger("altero.db")


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


#: The most values one statement takes from a list that grows with a library.
#: SQLite refuses a statement binding more than 32,766 values and asyncpg one
#: binding more than 32,767, so such a list is sent in pieces this size: well
#: below either, with room for whatever else the statement binds.
CHUNK = 10_000


def chunked[T](values: Sequence[T]) -> Iterator[Sequence[T]]:
    """Yield ``values`` in pieces of at most :data:`CHUNK`."""
    for start in range(0, len(values), CHUNK):
        yield values[start : start + CHUNK]


def id_list(ids: Collection[int]) -> BindParameter[Any]:
    """``ids`` for an ``IN`` that has to be one predicate, however many there are.

    Written into the statement as literals rather than bound, so no limit on
    bound values applies. Only for integers, which cannot carry anything but a
    number into the SQL text; a list of strings is sent in :func:`chunked`
    pieces instead.
    """
    return bindparam(None, sorted(ids), type_=Integer, expanding=True, literal_execute=True)


#: Rows each index is sampled for when SQLite gathers statistics. SQLite's own
#: recommendation for a statistics pass that has to stay cheap.
ANALYSIS_LIMIT = 400

#: Analyse every table whose statistics are missing or out of date -- not only
#: those this connection has queried, which on a pooled connection would often
#: be none. The mask SQLite recommends running when a connection opens.
OPTIMIZE = "PRAGMA optimize=0x10002"


def _configure_sqlite(engine: AsyncEngine) -> None:
    """Apply the settings SQLite needs to behave under concurrent writes.

    Three things are wrong with SQLite's defaults here:

    - Foreign keys are not enforced, so a dangling reference is stored silently
      and only surfaces on a backend that does check.
    - The rollback journal blocks readers while a write is in progress. WAL lets
      them run alongside it.
    - The planner has no statistics until somebody runs ``ANALYZE``, and guesses
      badly without them: a tag listing on a library of 30k items took 25 s. A
      connection gathers them when it opens, and :meth:`Database.optimize`
      keeps them current as the library grows.
    What is deliberately not done here is beginning every transaction with
    ``BEGIN IMMEDIATE``. It would close the remaining hole — a transaction that
    reads and then writes can fail outright when it upgrades its lock, which
    ``busy_timeout`` does not cover — but it takes the write lock for read-only
    transactions too, so a single long read blocks every writer. That is a worse
    trade than the hole it fills. The writes to a library close it themselves:
    ``services.writes.lock_library`` writes before it reads, taking the lock at
    the start of the request rather than partway through. A deployment serving
    more than one client at a time should still use PostgreSQL, where the row
    lock in the write path does the job properly.
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
        # Analysed from a sample of each index, so a large database pays a
        # bounded cost, and only where statistics are missing or a table has
        # grown or shrunk enough to make them misleading -- usually nothing.
        cursor.execute(f"PRAGMA analysis_limit={ANALYSIS_LIMIT}")
        try:
            cursor.execute(OPTIMIZE)
        except sqlite3.OperationalError:
            # Statistics are written, so this can find a long write holding the
            # database. A connection without them still works; the next one, or
            # the periodic run, catches up.
            logger.warning("Could not refresh SQLite's planner statistics", exc_info=True)
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

    async def optimize(self) -> int:
        """Refresh SQLite's planner statistics where a table has outgrown them.

        Run on a timer, because a pooled connection gathers statistics once
        when it opens and may then live as long as the process. Nothing for
        any other backend: PostgreSQL's autovacuum does this already.

        Returns zero, for :class:`~altero.services.groupsweeper.Sweeper`.
        """
        if self.engine.dialect.name == "sqlite":
            async with self.engine.connect() as connection:
                await connection.exec_driver_sql(OPTIMIZE)
        return 0

    async def create_all(self) -> None:
        """Create every table. Intended for tests; production uses Alembic."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
