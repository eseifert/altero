"""Index full text for substring search

A quick search in ``everything`` mode looks for ``%word%`` in every attachment's
full text, which no ordinary index answers: a rare word in a library of 10,000
texts read all 60 MB of them, 2.4 s on SQLite and 2.9 s on PostgreSQL. Each
backend gets the index that can answer it, and both are required:

- PostgreSQL: the ``pg_trgm`` and ``btree_gin`` extensions and a GIN index on
  ``item_fulltext`` over the library and the text. Both extensions are trusted
  since PostgreSQL 13, so the database owner may create them.
- SQLite: an FTS5 table with the ``trigram`` tokenizer (SQLite 3.34 or newer),
  reading its text from ``item_fulltext`` and kept in step by triggers.

The statements are written out here rather than imported from the models, so
that this revision stays what it was when the models move on.

Revision ID: a3f1c6d2e8b4
Revises: 8ec9c377b185
Create Date: 2026-10-19 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.exc import DBAPIError, OperationalError

# revision identifiers, used by Alembic.
revision: str = "a3f1c6d2e8b4"
down_revision: str | Sequence[str] | None = "8ec9c377b185"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH = "item_fulltext_search"

SQLITE_SEARCH = (
    f"CREATE VIRTUAL TABLE {SEARCH} USING fts5("
    "content, content='item_fulltext', content_rowid='item_id', tokenize='trigram')",
    f"CREATE TRIGGER {SEARCH}_insert AFTER INSERT ON item_fulltext BEGIN "
    f"INSERT INTO {SEARCH}(rowid, content) VALUES (new.item_id, new.content); END",
    f"CREATE TRIGGER {SEARCH}_delete AFTER DELETE ON item_fulltext BEGIN "
    f"INSERT INTO {SEARCH}({SEARCH}, rowid, content) "
    "VALUES ('delete', old.item_id, old.content); END",
    f"CREATE TRIGGER {SEARCH}_update AFTER UPDATE OF content ON item_fulltext BEGIN "
    f"INSERT INTO {SEARCH}({SEARCH}, rowid, content) "
    "VALUES ('delete', old.item_id, old.content); "
    f"INSERT INTO {SEARCH}(rowid, content) VALUES (new.item_id, new.content); END",
    # Everything already stored, read once from item_fulltext.
    f"INSERT INTO {SEARCH}({SEARCH}) VALUES ('rebuild')",
)


def _require_sqlite_trigrams() -> None:
    """Refuse, saying why, where SQLite cannot build the search table."""
    bind = op.get_bind()
    try:
        bind.exec_driver_sql(
            "CREATE VIRTUAL TABLE temp.altero_trigram_probe USING fts5(x, tokenize='trigram')"
        )
        bind.exec_driver_sql("DROP TABLE temp.altero_trigram_probe")
    except OperationalError as missing:
        version = bind.exec_driver_sql("SELECT sqlite_version()").scalar()
        raise RuntimeError(
            f"altero needs SQLite 3.34 or newer built with FTS5 for full-text search; "
            f"this Python uses SQLite {version}, which cannot create an FTS5 trigram "
            f"table ({missing.orig}). Use a Python linked against a newer SQLite, "
            f"or PostgreSQL."
        ) from None


def _require_extensions() -> None:
    """Create ``pg_trgm`` and ``btree_gin``, or refuse saying why one could not be."""
    for extension in ("pg_trgm", "btree_gin"):
        try:
            with op.get_context().autocommit_block():
                op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
        except DBAPIError as refused:
            raise RuntimeError(
                f"altero needs the PostgreSQL extension {extension} for full-text "
                f"search, and could not create it ({refused.orig}). Run "
                f"'CREATE EXTENSION {extension};' in altero's database as its owner "
                "or a superuser, then migrate again. On PostgreSQL 12 and older it "
                "needs a superuser; some distributions ship it in a separate contrib "
                "package."
            ) from None


def upgrade() -> None:
    """Upgrade schema."""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _require_sqlite_trigrams()
        for statement in SQLITE_SEARCH:
            op.execute(statement)
    elif dialect == "postgresql":
        _require_extensions()
        op.create_index(
            "ix_item_fulltext_library_content_trgm",
            "item_fulltext",
            ["library_id", "content"],
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        )


def downgrade() -> None:
    """Downgrade schema."""
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for trigger in ("insert", "delete", "update"):
            op.execute(f"DROP TRIGGER IF EXISTS {SEARCH}_{trigger}")
        op.execute(f"DROP TABLE IF EXISTS {SEARCH}")
    elif dialect == "postgresql":
        # The extensions stay: other things in the database may use them.
        op.drop_index("ix_item_fulltext_library_content_trgm", table_name="item_fulltext")
