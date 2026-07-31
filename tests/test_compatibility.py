"""Behaviours taken from the official dataserver rather than the documentation.

Each of these was read out of https://github.com/zotero/dataserver, because the
prose documentation either omits them or describes them differently. The Zotero
desktop application depends on them, so they are mirrored deliberately.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.query import ITEM_SORT_FIELDS, Direction, Format, parse_list_query
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user, tag_item

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestUnlimitedSyncFormats:
    """``Zotero_API::getLimitMax`` returns 0 for keys and versions.

    A limit of 0 means no maximum, and the default limit for those formats is
    also 0, so both are unpaginated. The desktop client reads the whole of
    ``format=versions`` to work out what changed, so truncating it to 25 would
    quietly break syncing.
    """

    async def test_format_versions_is_not_truncated(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(40):
            await make_item(session, library, key=f"AAA{index:05d}")

        body = (await client.get("/users/1/items?format=versions", headers=AUTH)).json()

        assert len(body) == 40

    async def test_format_keys_is_not_truncated(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(40):
            await make_item(session, library, key=f"AAA{index:05d}")

        response = await client.get("/users/1/items?format=keys", headers=AUTH)

        assert len(response.text.split("\n")) == 40

    async def test_json_is_still_paginated(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(40):
            await make_item(session, library, key=f"AAA{index:05d}")

        assert len((await client.get("/users/1/items", headers=AUTH)).json()) == 25

    async def test_an_unlimited_response_has_no_link_header(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(40):
            await make_item(session, library, key=f"AAA{index:05d}")

        response = await client.get("/users/1/items?format=versions", headers=AUTH)

        assert "Link" not in response.headers
        assert response.headers["Total-Results"] == "40"

    async def test_an_explicit_limit_is_still_honoured(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(40):
            await make_item(session, library, key=f"AAA{index:05d}")

        body = (await client.get("/users/1/items?format=versions&limit=10", headers=AUTH)).json()

        assert len(body) == 10

    async def test_a_limit_above_one_hundred_is_allowed_for_these_formats(self) -> None:
        query = parse_list_query(
            [("format", "versions"), ("limit", "5000")], sort_fields=ITEM_SORT_FIELDS
        )

        assert query.limit == 5000


class TestNegationCoversTheWholeExpression:
    """``getSearchParamValues`` strips the leading ``-`` before splitting on ``||``."""

    async def test_negated_item_types_exclude_every_alternative(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="book")
        await make_item(session, library, key="BBBB2345", item_type="journalArticle")
        await make_item(session, library, key="CCCC2345", item_type="thesis")

        body = (
            await client.get("/users/1/items?itemType=-book || journalArticle", headers=AUTH)
        ).json()

        assert [i["key"] for i in body] == ["CCCC2345"]

    async def test_negated_tags_exclude_every_alternative(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await make_item(session, library, key="CCCC2345")
        await tag_item(session, library, one, "fiction")
        await tag_item(session, library, two, "history")

        body = (await client.get("/users/1/items?tag=-fiction || history", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["CCCC2345"]

    async def test_a_bare_double_pipe_is_part_of_the_value(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "a||b")

        body = (await client.get("/users/1/items?tag=a||b", headers=AUTH)).json()

        assert [i["key"] for i in body] == ["AAAA2345"]


class TestParameterQuirks:
    async def test_a_direction_passed_as_sort_is_moved_across(self) -> None:
        # sort=asc means "default sort, ascending", not an invalid sort field.
        query = parse_list_query([("sort", "asc")], sort_fields=ITEM_SORT_FIELDS)

        assert query.sort == "dateModified"
        assert query.direction is Direction.ASCENDING

    async def test_sort_asc_is_accepted_over_http(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        assert (await client.get("/users/1/items?sort=asc", headers=AUTH)).status_code == 200

    @pytest.mark.parametrize("value", ["titleCreatorYear", "titlecreatoryear", "EVERYTHING"])
    async def test_qmode_is_matched_case_insensitively(self, value: str) -> None:
        # The reference implementation lowercases before comparing.
        query = parse_list_query([("qmode", value)], sort_fields=ITEM_SORT_FIELDS)

        assert query.qmode in ("titleCreatorYear", "everything")

    async def test_startswith_is_accepted_in_either_spelling(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "history")

        lower = await client.get("/users/1/tags?q=his&qmode=startswith", headers=AUTH)
        camel = await client.get("/users/1/tags?q=his&qmode=startsWith", headers=AUTH)

        assert lower.status_code == camel.status_code == 200
        assert lower.json() == camel.json() != []

    async def test_repeating_item_type_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items?itemType=book&itemType=thesis", headers=AUTH)

        assert response.status_code == 400
        assert response.text == "Cannot specify 'itemType' more than once"

    async def test_a_zero_limit_falls_back_to_the_default(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index in range(30):
            await make_item(session, library, key=f"AAA{index:05d}")

        body = (await client.get("/users/1/items?limit=0", headers=AUTH)).json()

        assert len(body) == 25

    async def test_date_prefixed_sorts_count_down_by_default(self) -> None:
        # Any field whose name starts with "date" defaults to descending.
        for sort in ("dateAdded", "dateModified", "date"):
            query = parse_list_query([("sort", sort)], sort_fields=ITEM_SORT_FIELDS)
            assert query.direction is Direction.DESCENDING, sort

        query = parse_list_query([("sort", "title")], sort_fields=ITEM_SORT_FIELDS)
        assert query.direction is Direction.ASCENDING

    @pytest.mark.parametrize("sort", ["extra", "serverDateModified"])
    async def test_extra_sort_fields_from_the_reference_are_accepted(self, sort: str) -> None:
        assert parse_list_query([("sort", sort)], sort_fields=ITEM_SORT_FIELDS).sort == sort

    async def test_num_items_is_not_a_valid_item_sort(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # numItems is only meaningful for tags.
        response = await client.get("/users/1/items?sort=numItems", headers=AUTH)

        assert response.status_code == 400


class TestFormatDefaults:
    def test_keys_and_versions_default_to_unlimited(self) -> None:
        from altero.pagination import UNLIMITED
        from altero.query import default_limit, limit_maximum

        for response_format in (Format.KEYS, Format.VERSIONS):
            assert default_limit(response_format) == UNLIMITED
            assert limit_maximum(response_format) == UNLIMITED

    def test_json_keeps_the_documented_bounds(self) -> None:
        from altero.query import default_limit, limit_maximum

        assert default_limit(Format.JSON) == 25
        assert limit_maximum(Format.JSON) == 100
