"""Create isolated PostgreSQL databases without touching an existing library."""

import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tools.compatibility.client import CompatibilityError


async def fresh_database(root: Path, admin_url: str) -> str:
    """Preserve each database for inspection, including failed acceptance runs."""
    url = make_url(admin_url)
    if url.drivername != "postgresql+asyncpg":
        raise CompatibilityError("--postgres-url requires a postgresql+asyncpg URL")
    name = f"altero_acceptance_{uuid4().hex}"
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            # The identifier is generated here, never supplied by the caller.
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()
    (root / "database.json").write_text(json.dumps(dict(backend="postgresql", name=name)) + "\n")
    return url.set(database=name).render_as_string(hide_password=False)
