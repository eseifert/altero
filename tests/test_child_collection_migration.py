"""Repair already-synced child collection memberships without hiding the repair."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from altero.settings import get_settings


def test_upgrade_removes_child_memberships_and_versions_only_affected_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "upgraded.sqlite"
    monkeypatch.setenv("ALTERO_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    try:
        command.upgrade(config, "ae39b4d8c021")
        with sqlite3.connect(path) as db:
            for library_id in (1, 2, 3):
                db.execute(
                    "INSERT INTO libraries (id, type, owner_id, name, version, public) "
                    "VALUES (?, 'USER', ?, '', ?, 0)",
                    (library_id, library_id, library_id * 10),
                )
                db.execute(
                    "INSERT INTO collections (id, library_id, key, version, name, deleted, "
                    "date_added, date_modified, server_date_modified) VALUES "
                    "(?, ?, 'CCCC2345', 1, 'Papers', 0, '2026-01-01', '2026-01-01', '2026-01-01')",
                    (library_id, library_id),
                )
            for item_id, library_id, item_type, parent, deleted in (
                (1, 1, "book", None, 0),
                (2, 1, "attachment", 1, 0),
                (3, 1, "note", 1, 1),
                (4, 1, "note", 1, 0),  # A valid child must keep its version.
                (5, 2, "book", None, 0),
                (6, 2, "attachment", 5, 0),
                (7, 3, "attachment", None, 0),
            ):
                db.execute(
                    "INSERT INTO items (id, library_id, key, version, item_type, parent_id, "
                    "deleted, "
                    "in_publications, sort_title, sort_creator, sort_date, date_added, "
                    "date_modified, server_date_modified) VALUES "
                    "(?, ?, ?, 5, ?, ?, ?, 0, '', '', '', "
                    "'2026-01-01', '2026-01-01', '2026-01-01')",
                    (item_id, library_id, f"AAAA234{item_id}", item_type, parent, deleted),
                )
            db.executemany(
                "INSERT INTO collection_items (collection_id, item_id) VALUES (?, ?)",
                [(1, 1), (1, 2), (1, 3), (2, 6), (3, 7)],
            )
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT collection_id, item_id FROM collection_items ORDER BY item_id"
        ).fetchall() == [
            (1, 1),
            (3, 7),
        ]
        assert dict(db.execute("SELECT id, version FROM libraries")) == {1: 11, 2: 21, 3: 30}
        assert dict(db.execute("SELECT id, version FROM items")) == {
            1: 5,
            2: 11,
            3: 11,
            4: 5,
            5: 5,
            6: 21,
            7: 5,
        }
        for item_id, parent, deleted, modified, server_modified in db.execute(
            "SELECT id, parent_id, deleted, date_modified, server_date_modified FROM items"
        ):
            assert modified == "2026-01-01"
            if item_id in (2, 3, 6):
                assert parent is not None
                assert server_modified > "2026-01-01"
            else:
                assert server_modified == "2026-01-01"
            assert bool(deleted) == (item_id == 3)
