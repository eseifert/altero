"""An item search ignores case in every alphabet; a tag search never does.

SQLite's own ``lower()`` and ``LIKE`` fold ASCII letters only unless SQLite was
built with ICU -- the Debian build in the container image is not -- so these
failed there while passing on a developer's ICU build. They run on both
backends: SQLite always, PostgreSQL when ``ALTERO_TEST_POSTGRES_URL`` is set.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import Base, Database
from altero.models import Library, LibraryType
from altero.query import ListQuery, QuickSearchMode, TagSearchMode
from altero.services import items, tags
from altero.services.auth import get_library
from altero.services.items import Scope
from altero.settings import Settings
from tests.factories import index_fulltext, make_item, make_user, tag_item

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


async def found(
    session: AsyncSession, library: Library, words: str, *, everything: bool = False
) -> set[str]:
    """The keys of the items a quick search answers with."""
    mode = QuickSearchMode.EVERYTHING if everything else QuickSearchMode.TITLE_CREATOR_YEAR
    query = ListQuery(q=words, qmode=mode, limit=50)
    page = await items.list_items(session, library, query, scope=Scope.ALL)
    return {item.key for item in page.objects}


async def found_tags(
    session: AsyncSession, library: Library, words: str, mode: str = TagSearchMode.CONTAINS
) -> set[str]:
    """The names of the tags a tag search answers with."""
    page = await tags.list_tags(session, library, ListQuery(q=words, qmode=mode, limit=50))
    return {tag.name for tag in page.objects}


class TestItems:
    async def test_a_title_matches_in_either_case(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="UBER2345", fields={"title": "Über die Freiheit"})
        await make_item(session, library, key="OTHER234", fields={"title": "On Liberty"})

        assert await found(session, library, "über") == {"UBER2345"}
        assert await found(session, library, "ÜBER") == {"UBER2345"}

    async def test_a_title_under_another_field_name_matches_in_either_case(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="CASE2345",
            item_type="case",
            fields={"caseName": "ÖSTERREICHISCHER RUNDFUNK v. AUSTRIA"},
        )

        assert await found(session, library, "österreichischer") == {"CASE2345"}

    async def test_a_creator_matches_in_either_case(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="ZULA2345",
            fields={"title": "Na srebrnym globie"},
            creators=[("author", "Jerzy", "ŻUŁAWSKI")],
        )

        assert await found(session, library, "żuławski") == {"ZULA2345"}

    async def test_other_alphabets_fold_too(self, session: AsyncSession, library: Library) -> None:
        await make_item(
            session, library, key="CRIM2345", fields={"title": "ПРЕСТУПЛЕНИЕ И НАКАЗАНИЕ"}
        )
        await make_item(session, library, key="ODYS2345", fields={"title": "ΟΔΥΣΣΕΙΑ"})

        assert await found(session, library, "наказание") == {"CRIM2345"}
        assert await found(session, library, "οδυσσεια") == {"ODYS2345"}

    async def test_a_field_searched_only_in_everything_mode_folds_too(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="GALL2345",
            fields={"title": "L'Étranger", "publisher": "ÉDITIONS GALLIMARD"},
        )

        assert await found(session, library, "éditions") == set()
        assert await found(session, library, "éditions", everything=True) == {"GALL2345"}

    async def test_a_term_too_short_for_the_text_index_folds_too(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="UBUN2345", item_type="attachment")
        await index_fulltext(session, library, item, "ÜBUNGEN ZUR ANALYSIS")

        assert await found(session, library, "üb", everything=True) == {"UBUN2345"}

    async def test_an_ascii_term_still_ignores_ascii_case(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="MOBY2345", fields={"title": "MOBY-DICK"})

        assert await found(session, library, "moby") == {"MOBY2345"}

    async def test_wildcards_keep_their_meaning_beside_a_folded_letter(
        self, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="UBER2345", fields={"title": "ÜBER ALLES"})

        assert await found(session, library, "ü_er") == {"UBER2345"}
        assert await found(session, library, "ü%alles") == {"UBER2345"}


class TestTags:
    """A tag search minds case, as zotero.org's and the desktop's Local API's both do.

    The dataserver matches ``name LIKE ?`` against a binary collation, so its
    wildcards and backslash escape carry over; only the folding does not.
    """

    async def test_case_must_match_in_every_alphabet(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="ECOL2345")
        await tag_item(session, library, item, "Ökologie")
        await tag_item(session, library, item, "Fiction")

        assert await found_tags(session, library, "Ökol") == {"Ökologie"}
        assert await found_tags(session, library, "ökol") == set()
        assert await found_tags(session, library, "Fic") == {"Fiction"}
        assert await found_tags(session, library, "fic") == set()

    async def test_starts_with_minds_case_too(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="ECOL2345")
        await tag_item(session, library, item, "Ökologie")
        await tag_item(session, library, item, "Ökonomie")
        await tag_item(session, library, item, "Agrarökonomie")

        assert await found_tags(session, library, "Öko", TagSearchMode.STARTS_WITH) == {
            "Ökologie",
            "Ökonomie",
        }
        assert await found_tags(session, library, "öko", TagSearchMode.STARTS_WITH) == set()

    async def test_like_wildcards_are_wildcards(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="WILD2345")
        await tag_item(session, library, item, "colour")
        await tag_item(session, library, item, "color")

        assert await found_tags(session, library, "col_r") == {"color"}
        assert await found_tags(session, library, "col%r") == {"colour", "color"}

    async def test_a_backslash_escapes_a_wildcard(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="ESCA2345")
        await tag_item(session, library, item, "50%")
        await tag_item(session, library, item, "500")

        assert await found_tags(session, library, "50\\%") == {"50%"}

    async def test_other_pattern_characters_are_literal(
        self, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="GLOB2345")
        await tag_item(session, library, item, "a*b")
        await tag_item(session, library, item, "a?b")
        await tag_item(session, library, item, "[draft]")
        await tag_item(session, library, item, "axb")

        assert await found_tags(session, library, "*") == {"a*b"}
        assert await found_tags(session, library, "?") == {"a?b"}
        assert await found_tags(session, library, "[d") == {"[draft]"}
