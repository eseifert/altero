"""Full-text content extracted from attachments.

The text is searched by substring -- a quick search in ``everything`` mode asks
for ``%word%`` -- which no ordinary index can answer. Each backend gets the
index that can, and both are required rather than optional:

- PostgreSQL: a GIN index on the library and the text, from the ``pg_trgm``
  and ``btree_gin`` extensions, which serves the ``ILIKE`` the search already
  uses. The library is in it because every text a trigram lookup finds is read
  again to be checked: without it a common word read every library's.
- SQLite: an FTS5 table with the ``trigram`` tokenizer (SQLite 3.34 or newer)
  holding no copy of the text -- ``content=`` points it at this table -- and
  kept in step by triggers, so every path that writes full text keeps it
  current: an upload, a delete, a restore, a migration from zotero.org.

The migration that introduced them is ``a3f1c6d2e8b4``. The same objects are
declared here so that ``create_all`` -- the tests, a fresh database built
without Alembic -- has them too.
"""

from sqlalchemy import DDL, ForeignKey, Index, Text, event
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import column, table

from altero.db import Base

#: The SQLite search table, by the name the queries use.
SEARCH_TABLE = "item_fulltext_search"

#: The SQLite search table as something a query can select from. The column
#: named after the table is FTS5's own, the left-hand side of a ``MATCH``.
search_table = table(SEARCH_TABLE, column("rowid"), column("content"), column(SEARCH_TABLE))

#: What creates the SQLite search table and keeps it in step, in order.
SQLITE_SEARCH_DDL = (
    f"CREATE VIRTUAL TABLE {SEARCH_TABLE} USING fts5("
    "content, content='item_fulltext', content_rowid='item_id', tokenize='trigram')",
    f"CREATE TRIGGER {SEARCH_TABLE}_insert AFTER INSERT ON item_fulltext BEGIN "
    f"INSERT INTO {SEARCH_TABLE}(rowid, content) VALUES (new.item_id, new.content); END",
    f"CREATE TRIGGER {SEARCH_TABLE}_delete AFTER DELETE ON item_fulltext BEGIN "
    f"INSERT INTO {SEARCH_TABLE}({SEARCH_TABLE}, rowid, content) "
    "VALUES ('delete', old.item_id, old.content); END",
    f"CREATE TRIGGER {SEARCH_TABLE}_update AFTER UPDATE OF content ON item_fulltext BEGIN "
    f"INSERT INTO {SEARCH_TABLE}({SEARCH_TABLE}, rowid, content) "
    "VALUES ('delete', old.item_id, old.content); "
    f"INSERT INTO {SEARCH_TABLE}(rowid, content) VALUES (new.item_id, new.content); END",
)


class FullText(Base):
    """The searchable text of one attachment.

    The client extracts this from a PDF or web page and uploads it so that
    searching works on every device, not only the one holding the file.
    """

    __tablename__ = "item_fulltext"
    __table_args__ = (
        Index("ix_item_fulltext_library_version", "library_id", "version"),
        Index(
            "ix_item_fulltext_library_content_trgm",
            "library_id",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"))
    content: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(default=1)

    #: How much of the document was indexed. Which pair applies depends on the
    #: document: pages for paginated formats, characters otherwise.
    indexed_chars: Mapped[int | None] = mapped_column()
    total_chars: Mapped[int | None] = mapped_column()
    indexed_pages: Mapped[int | None] = mapped_column()
    total_pages: Mapped[int | None] = mapped_column()


for _extension in ("pg_trgm", "btree_gin"):
    event.listen(
        Base.metadata,
        "before_create",
        DDL(f"CREATE EXTENSION IF NOT EXISTS {_extension}").execute_if(dialect="postgresql"),
    )
for _statement in SQLITE_SEARCH_DDL:
    event.listen(FullText.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
event.listen(
    FullText.__table__,
    "before_drop",
    DDL(f"DROP TABLE IF EXISTS {SEARCH_TABLE}").execute_if(dialect="sqlite"),
)
