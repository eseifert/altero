"""Alembic environment.

The database URL is taken from altero's own settings rather than ``alembic.ini``,
so migrations always target the same database the application uses.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from altero.db import Base
from altero.models import *  # noqa: F403  (import models so autogenerate sees them)
from altero.models.fulltext import SEARCH_TABLE
from altero.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, _parents: object) -> bool:
    """Leave SQLite's full-text search table out of the comparison.

    An FTS5 table is a virtual table with shadow tables of its own, none of
    which the models describe as tables: ``models/fulltext.py`` creates them,
    and autogenerate would otherwise offer to drop them.
    """
    return not (type_ == "table" and name is not None and name.startswith(SEARCH_TABLE))


def include_object(
    object_: object, _name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    """Leave out an index the models create on another backend only.

    ``Index.ddl_if`` keeps the full-text trigram index off SQLite in
    ``create_all``, and autogenerate does not read it; without this it would
    offer SQLite an index of PostgreSQL's.
    """
    condition = getattr(object_, "_ddl_if", None)
    if type_ != "index" or condition is None or condition.dialect is None:
        return True
    return context.get_context().dialect.name == condition.dialect


def run_migrations_offline() -> None:
    """Run migrations without a DBAPI connection, emitting SQL to stdout."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        include_name=include_name,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Batch mode lets SQLite emulate the ALTER TABLE statements it lacks.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=include_name,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
