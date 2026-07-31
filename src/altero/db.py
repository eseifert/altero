"""Database engine, session factory and ORM base class."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from altero.settings import Settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


class Database:
    """Owns the async engine and hands out sessions."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
        )
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
