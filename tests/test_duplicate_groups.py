"""The browser pages complete duplicate groups, independently of item pages."""

from datetime import datetime

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library
from altero.services import admin
from tests import factories
from tests.test_web_routes import register


async def seed(client: httpx2.AsyncClient, session: AsyncSession) -> tuple[int, list[str]]:
    await register(client)
    library = await session.scalar(select(Library).where(Library.owner_id == 1))
    assert library is not None
    keys = []
    for title, doi, year, added in [
        ("Alpha", "10.1234/shared", "2000", 2022),
        ("Beta", "10.1234/shared", "2000", 2020),
        ("Beta", "10.1234/other", "2000", 2021),
        ("Gamma", "", "2010", 2024),
        ("Gamma", "", "2010", 2023),
    ]:
        item = await factories.make_item(
            session,
            library,
            item_type="journalArticle",
            fields={"title": title, "DOI": doi, "date": year},
        )
        item.date_added = datetime(added, 1, 1)
        keys.append(item.key)
    await session.commit()
    return library.id, keys


async def test_groups_follow_matching_links_and_put_the_oldest_first(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    library, keys = await seed(client, session)
    response = await client.get(
        f"/web/libraries/{library}/items?scope=duplicates&grouped=true&sort=title&direction=asc&limit=1"
    )
    body = response.json()
    assert response.status_code == 200
    assert body.get("groups") == [[keys[1], keys[2], keys[0]]]
    assert body["total"] == 5
    assert body["totalGroups"] == 2
    second = (
        await client.get(
            f"/web/libraries/{library}/items?scope=duplicates&grouped=true&sort=title&direction=asc&limit=1&start=1"
        )
    ).json()
    assert second["groups"] == [[keys[4], keys[3]]]
    assert [row["key"] for row in second["items"]] == [keys[4], keys[3]]


async def test_search_finds_the_whole_group_and_legacy_item_paging_stays_available(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    library, keys = await seed(client, session)
    body = (
        await client.get(
            f"/web/libraries/{library}/items?scope=duplicates&grouped=true&q=Beta&limit=1"
        )
    ).json()
    assert body.get("groups") == [[keys[1], keys[2], keys[0]]]
    assert len(body["items"]) == 3
    assert body["totalGroups"] == 1
    legacy = (
        await client.get(f"/web/libraries/{library}/items?scope=duplicates&q=Beta&limit=1")
    ).json()
    assert len(legacy["items"]) == 1
    assert legacy["total"] == 2
    assert "groups" not in legacy


async def test_grouping_requires_the_duplicates_scope_and_library_access(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    library, _ = await seed(client, session)
    assert (await client.get(f"/web/libraries/{library}/items?grouped=true")).status_code == 400
    stranger = await admin.create_user(session, username="grace")
    other = await session.scalar(select(Library).where(Library.owner_id == stranger.id))
    assert other is not None
    assert (
        await client.get(f"/web/libraries/{other.id}/items?scope=duplicates&grouped=true")
    ).status_code == 403


async def test_grouped_export_includes_members_that_did_not_match_the_search(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    library, _ = await seed(client, session)
    response = await client.get(
        f"/web/libraries/{library}/items/export?scope=duplicates&grouped=true&q=Beta&format=ris"
    )
    assert response.status_code == 200
    assert response.text.count("TY  - ") == 3
    assert "Alpha" in response.text
    assert (
        await client.get(f"/web/libraries/{library}/items/export?grouped=true&format=ris")
    ).status_code == 400
