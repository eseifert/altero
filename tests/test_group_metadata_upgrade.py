"""Existing desktop clients must re-fetch the corrected membership metadata."""

from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_upgrade_refreshes_only_groups_and_downgrade_keeps_versions_monotonic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module("migrations.versions.e97b23a41d06_refresh_group_membership_metadata")
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE libraries (id INTEGER PRIMARY KEY, version INTEGER)"))
        connection.execute(text("CREATE TABLE groups (library_id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO libraries VALUES (1, 7), (2, 12), (3, 0)"))
        connection.execute(text("INSERT INTO groups VALUES (2), (3)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

        migration.upgrade()
        expected = [(1, 7), (2, 13), (3, 1)]
        assert (
            list(connection.execute(text("SELECT id, version FROM libraries ORDER BY id")))
            == expected
        )
        migration.downgrade()
        assert (
            list(connection.execute(text("SELECT id, version FROM libraries ORDER BY id")))
            == expected
        )
