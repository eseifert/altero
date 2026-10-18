"""Searching attachments' full text through each backend's index.

A quick search in ``everything`` mode looks for a substring of every
attachment's text. PostgreSQL answers it from a trigram GIN index and SQLite
from an FTS5 trigram table kept in step by triggers -- see
``models/fulltext.py``. These run on both: SQLite always, PostgreSQL when
``ALTERO_TEST_POSTGRES_URL`` is set, which CI does.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Base, Database
from altero.models import FullText, Library, LibraryType
from altero.query import ListQuery, QuickSearchMode
from altero.services import items
from altero.services.auth import get_library
from altero.services.items import Scope
from altero.services.itemwrites import delete_items
from altero.settings import Settings
from tests.factories import index_fulltext, make_item, make_user

POSTGRES_URL = os.environ.get("ALTERO_TEST_POSTGRES_URL")

BACKENDS = [
    "sqlite",
    pytest.param(
        "postgresql",
        marks=pytest.mark.skipif(not POSTGRES_URL, reason="ALTERO_TEST_POSTGRES_URL is not set"),
    ),
]


@pytest.fixture(params=BACKENDS)
async def database(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Database]:
    if request.param == "sqlite":
        database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))
    else:
        assert POSTGRES_URL
        database = Database(Settings(database_url=POSTGRES_URL))
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as session:
        yield session


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    return await get_library(session, LibraryType.USER, 1)


async def found(session: AsyncSession, library: Library, words: str) -> set[str]:
    """The keys of the items a search of everything answers with."""
    query = ListQuery(q=words, qmode=QuickSearchMode.EVERYTHING, limit=50)
    page = await items.list_items(session, library, query, scope=Scope.ALL)
    return {item.key for item in page.objects}


async def attachment(session: AsyncSession, library: Library, key: str, content: str) -> None:
    item = await make_item(session, library, key=key, item_type="attachment")
    await index_fulltext(session, library, item, content)


class TestFindingText:
    async def test_a_word_only_in_the_text_is_found(
        self, session: AsyncSession, library: Library
    ) -> None:
        await attachment(session, library, "MOBY2345", "Call me Ishmael. Some years ago")
        await attachment(session, library, "OTHER234", "It was the best of times")

        assert await found(session, library, "ishmael") == {"MOBY2345"}

    async def test_case_does_not_matter_beyond_ascii_either(
        self, session: AsyncSession, library: Library
    ) -> None:
        """The trigram index folds Unicode case itself, however SQLite was built.

        SQLite's own ``lower()`` folds ASCII only unless it was built with ICU --
        the Debian build in the container image was not -- so this failed there
        before the index and passes on an ICU build either way.
        """
        await attachment(session, library, "UBER2345", "ÜBER DIE FREIHEIT")

        assert await found(session, library, "über") == {"UBER2345"}
        assert await found(session, library, "FREIHEIT") == {"UBER2345"}

    async def test_a_term_too_short_for_the_index_still_matches(
        self, session: AsyncSession, library: Library
    ) -> None:
        """Trigrams need three characters; a shorter term is answered by scanning."""
        await attachment(session, library, "SHORT234", "pi is about 3.14")

        assert await found(session, library, "pi") == {"SHORT234"}

    async def test_a_double_quote_is_a_character_like_any_other(
        self, session: AsyncSession, library: Library
    ) -> None:
        """SQLite asks for the part as an FTS5 phrase, whose own quotes it must not end."""
        await attachment(session, library, "QUOTE234", 'the O"Brien papers')
        await attachment(session, library, "OTHER234", "the OBrien papers")

        assert await found(session, library, 'O"Brien') == {"QUOTE234"}

    async def test_wildcards_match_in_the_text_as_in_the_fields(
        self, session: AsyncSession, library: Library
    ) -> None:
        """``%`` and ``_`` were never escaped, so they stay wildcards here too."""
        await attachment(session, library, "WILD2345", "the colour of money")

        assert await found(session, library, "col_ur") == {"WILD2345"}
        assert await found(session, library, "colour%money") == {"WILD2345"}

    async def test_another_librarys_text_is_not_found(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_user(session, user_id=2, username="other")
        other = await get_library(session, LibraryType.USER, 2)
        await attachment(session, other, "ELSE2345", "Call me Ishmael")

        assert await found(session, library, "ishmael") == set()


class TestKeepingInStep:
    async def test_changed_text_is_searched_as_it_now_reads(
        self, session: AsyncSession, library: Library
    ) -> None:
        await attachment(session, library, "MOBY2345", "Call me Ishmael")

        await session.execute(
            update(FullText).values(content="The whale, the whale").where(FullText.item_id > 0)
        )
        await session.commit()

        assert await found(session, library, "ishmael") == set()
        assert await found(session, library, "whale") == {"MOBY2345"}

    async def test_a_deleted_item_leaves_nothing_behind(
        self, session: AsyncSession, library: Library
    ) -> None:
        await attachment(session, library, "MOBY2345", "Call me Ishmael")

        await delete_items(session, library, ["MOBY2345"], 5)
        await session.commit()

        assert await found(session, library, "ishmael") == set()

    async def test_text_written_in_bulk_is_found(
        self, session: AsyncSession, library: Library
    ) -> None:
        """What a restore and a migration from zotero.org do: rows, no ORM objects."""
        item = await make_item(session, library, key="BULK2345", item_type="attachment")
        await session.execute(
            insert(FullText),
            [{"item_id": item.id, "library_id": library.id, "content": "Call me Ishmael"}],
        )
        await session.commit()

        assert await found(session, library, "ishmael") == {"BULK2345"}


class TestTheIndex:
    async def test_the_search_is_answered_from_the_index(
        self, session: AsyncSession, library: Library, database: Database
    ) -> None:
        if database.engine.dialect.name == "sqlite":
            plan = await session.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT rowid FROM item_fulltext_search "
                    "WHERE content LIKE '%ishmael%'"
                )
            )
            assert any("VIRTUAL TABLE INDEX" in str(row[-1]) for row in plan)
        else:
            names = await session.scalars(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'item_fulltext'")
            )
            assert "ix_item_fulltext_library_content_trgm" in set(names)


def test_upgrading_indexes_the_text_already_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migration builds the search table from what is there, not only from what comes."""
    import sqlite3

    from alembic import command
    from alembic.config import Config

    from altero.settings import get_settings

    path = tmp_path / "upgraded.sqlite"
    monkeypatch.setenv("ALTERO_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    # No alembic.ini: its logging section would disable every logger already
    # made, and later tests reading the log through caplog would find nothing.
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent.parent / "migrations")
    )
    try:
        command.upgrade(config, "8ec9c377b185")
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO item_fulltext (item_id, library_id, content, version) "
                "VALUES (1, 1, 'Call me Ishmael', 1)"
            )
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()

    with sqlite3.connect(path) as connection:
        found = connection.execute(
            "SELECT rowid FROM item_fulltext_search WHERE content LIKE '%ishmael%'"
        ).fetchall()
    assert found == [(1,)]
