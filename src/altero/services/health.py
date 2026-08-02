"""What an orchestrator needs to know before it routes traffic here.

A process that accepts connections is not the same as a server that can answer
them: without the database there is nothing to serve, and an instance that says
otherwise gets sent work it will only fail. The check is therefore a real query,
not a constant.
"""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from altero import API_VERSION, __version__
from altero.itemschema import get_schema


async def migration_revision(session: AsyncSession) -> str | None:
    """Return the Alembic revision this database is stamped with.

    ``None`` when nothing stamped it -- a database built by ``create_all()``,
    as the test suite does, or one that predates migrations. Reporting the
    absence is more use than inventing a revision, because "which migration is
    this instance on" is the question asked during an upgrade.
    """
    try:
        return await session.scalar(
            select(text("version_num")).select_from(text("alembic_version"))
        )
    except SQLAlchemyError:
        return None


async def check(session: AsyncSession) -> dict[str, Any]:
    """Return the readiness report, or raise if the database cannot answer."""
    # Cheapest statement that still proves a connection was opened and used.
    await session.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "version": __version__,
        "apiVersion": API_VERSION,
        "schemaVersion": get_schema().version,
        "revision": await migration_revision(session),
    }
