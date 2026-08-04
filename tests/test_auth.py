"""Credential handling and the key and group endpoints, over HTTP."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_api_key, make_group, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"


async def _setup(session: AsyncSession) -> None:
    await make_user(session, user_id=1, username="octocat", display_name="Mona Lisa")
    await make_api_key(session, key=KEY, user_id=1)


async def test_the_api_key_header_authenticates(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 200


async def test_a_bearer_token_authenticates(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups", headers={"Authorization": f"Bearer {KEY}"})

    assert response.status_code == 200


async def test_the_bearer_scheme_is_matched_case_insensitively(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups", headers={"Authorization": f"bearer {KEY}"})

    assert response.status_code == 200


async def test_the_key_query_parameter_authenticates(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get(f"/users/1/groups?key={KEY}")

    assert response.status_code == 200


async def test_the_header_wins_over_the_query_parameter(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups?key=WRONG", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 200


async def test_an_unknown_key_is_rejected(client: httpx.AsyncClient, session: AsyncSession) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups", headers={"Zotero-API-Key": "NOPE"})

    assert response.status_code == 403
    assert response.text == "Invalid key"
    assert response.headers["content-type"].startswith("text/plain")


async def test_a_missing_key_is_rejected(client: httpx.AsyncClient, session: AsyncSession) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups")

    assert response.status_code == 403


async def test_a_non_bearer_authorization_header_is_ignored(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups", headers={"Authorization": f"Basic {KEY}"})

    assert response.status_code == 403


async def test_a_key_cannot_list_another_users_groups(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)
    await make_user(session, user_id=2, username="other")

    response = await client.get("/users/2/groups", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 403


async def test_groups_are_listed_for_their_member(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)
    await make_group(session, group_id=100, owner_id=1, name="Research")

    response = await client.get("/users/1/groups", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 200
    (group,) = response.json()
    assert group["id"] == 100
    assert group["data"]["name"] == "Research"
    assert group["data"]["owner"] == 1
    assert group["links"]["self"]["href"].endswith("/groups/100")


async def test_one_group_is_readable_by_a_key_that_covers_it(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, user_id=1, username="octocat", display_name="Mona Lisa")
    await make_api_key(session, key=KEY, user_id=1, all_groups_read=True)
    await make_group(session, group_id=100, owner_id=1, name="Research")

    response = await client.get("/groups/100", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 100
    assert body["data"]["name"] == "Research"
    assert response.headers["Last-Modified-Version"] == "0"


async def test_a_public_group_is_readable_without_a_key(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)
    await make_group(session, group_id=100, owner_id=1, name="Open", public=True)

    response = await client.get("/groups/100")

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Open"


async def test_a_group_the_caller_cannot_read_is_not_confirmed_to_exist(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """403 would tell a stranger which private groups exist. Upstream's own
    check answers 404, and so does this. A key that does not cover groups is
    such a stranger even to its owner's own groups."""
    await _setup(session)
    await make_user(session, user_id=2, username="other")
    await make_group(session, group_id=100, owner_id=2, name="Theirs")

    response = await client.get("/groups/100", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 404


async def test_groups_of_other_users_are_not_listed(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)
    await make_user(session, user_id=2, username="other")
    await make_group(session, group_id=100, owner_id=2, name="Theirs")

    response = await client.get("/users/1/groups", headers={"Zotero-API-Key": KEY})

    assert response.json() == []


async def test_a_key_describes_its_own_access(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get(f"/keys/{KEY}", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == KEY
    assert body["userID"] == 1
    assert body["username"] == "octocat"
    assert body["displayName"] == "Mona Lisa"
    assert body["access"]["user"] == {
        "library": True,
        "files": True,
        "notes": True,
        "write": True,
    }


async def test_a_key_cannot_describe_another_key(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)
    await make_api_key(session, key="OTHERKEY", user_id=1)

    response = await client.get("/keys/OTHERKEY", headers={"Zotero-API-Key": KEY})

    assert response.status_code == 403


async def test_group_defaults_appear_in_the_key_description(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1, all_groups_read=True, all_groups_write=True)

    response = await client.get(f"/keys/{KEY}", headers={"Zotero-API-Key": KEY})

    assert response.json()["access"]["groups"]["all"] == {"library": True, "write": True}


async def test_every_response_carries_the_api_version(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _setup(session)

    response = await client.get("/users/1/groups", headers={"Zotero-API-Key": KEY})

    assert response.headers["Zotero-API-Version"] == "3"
