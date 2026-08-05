"""Who created and who last changed each item.

Upstream keeps this in a `groupItems` table and serialises it as
`meta.createdByUser` and `meta.lastModifiedByUser` (`Zotero_Item::toResponseJSON`
in `model/Item.inc.php`). Three rules come from there and are copied rather
than reasoned about:

- **Group libraries only.** A personal library has one author, and upstream
  emits neither field there.
- **`lastModifiedByUser` is omitted when it equals `createdByUser`.** The
  common case -- somebody adding an item and then fixing its title -- carries
  one name, not the same name twice.
- **A departed account does not break the item.** Upstream swallows the lookup
  failure if the user no longer exists.

What is deliberately different is `links`. Upstream gives each user an
`alternate` link to their profile on zotero.org; `docs/compatibility.md` records
why altero omits `alternate` links everywhere.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library
from tests.factories import make_api_key, make_group, make_user

ALICE = "AliceKeyAliceKeyAliceKey"
BOB = "BobKeyBobKeyBobKeyBobKey"

AS_ALICE = {"Zotero-API-Key": ALICE}
AS_BOB = {"Zotero-API-Key": BOB}
JSON = {"Content-Type": "application/json"}


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    """Alice owns a group; Bob is a member. Both keys reach groups."""
    for user_id, name, key in ((1, "alice", ALICE), (2, "bob", BOB)):
        await make_user(session, user_id=user_id, username=name, display_name=name.title())
        await make_api_key(
            session, key=key, user_id=user_id, all_groups_read=True, all_groups_write=True
        )
    return await make_group(session, group_id=100, owner_id=1, members={2: "member"})


async def create(client: httpx.AsyncClient, headers: dict[str, str], **fields: object) -> dict:
    payload = {"itemType": "book", "title": "One", **fields}
    response = await client.post("/groups/100/items", headers=headers | JSON, json=[payload])
    assert response.status_code == 200, response.text
    return response.json()["successful"]["0"]


async def read(client: httpx.AsyncClient, key: str, headers: dict[str, str]) -> dict:
    response = await client.get(f"/groups/100/items/{key}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestWhoCreated:
    async def test_the_creator_is_reported(self, client: httpx.AsyncClient, group: Library) -> None:
        created = await create(client, AS_ALICE)

        body = await read(client, created["key"], AS_ALICE)

        assert body["meta"]["createdByUser"] == {
            "id": 1,
            "username": "alice",
            "name": "Alice",
        }

    async def test_it_is_reported_on_a_listing_too(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        await create(client, AS_ALICE)

        listing = (await client.get("/groups/100/items", headers=AS_ALICE)).json()

        assert listing[0]["meta"]["createdByUser"]["username"] == "alice"

    async def test_the_creator_does_not_change_when_somebody_else_edits(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        created = await create(client, AS_ALICE)

        await client.post(
            "/groups/100/items",
            headers=AS_BOB | JSON,
            json=[{**created["data"], "title": "Two"}],
        )

        body = await read(client, created["key"], AS_ALICE)
        assert body["meta"]["createdByUser"]["username"] == "alice"

    async def test_a_personal_library_reports_neither(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # Upstream emits these for group libraries only: a personal library has
        # exactly one author and saying so on every item is noise.
        response = await client.post(
            "/users/1/items", headers=AS_ALICE | JSON, json=[{"itemType": "book", "title": "One"}]
        )
        key = response.json()["successful"]["0"]["key"]

        body = (await client.get(f"/users/1/items/{key}", headers=AS_ALICE)).json()

        assert "createdByUser" not in body["meta"]
        assert "lastModifiedByUser" not in body["meta"]


class TestWhoLastChanged:
    async def test_a_second_person_editing_is_reported(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        created = await create(client, AS_ALICE)

        await client.post(
            "/groups/100/items",
            headers=AS_BOB | JSON,
            json=[{**created["data"], "title": "Two"}],
        )

        body = await read(client, created["key"], AS_ALICE)
        assert body["meta"]["lastModifiedByUser"]["username"] == "bob"

    async def test_it_is_omitted_when_it_is_the_creator(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # Upstream's `$lastModifiedByUserID != $createdByUserID`. Adding an item
        # and then fixing its title is one name, not the same name twice.
        created = await create(client, AS_ALICE)

        await client.post(
            "/groups/100/items",
            headers=AS_ALICE | JSON,
            json=[{**created["data"], "title": "Two"}],
        )

        body = await read(client, created["key"], AS_ALICE)
        assert body["meta"]["createdByUser"]["username"] == "alice"
        assert "lastModifiedByUser" not in body["meta"]

    async def test_it_is_omitted_on_a_freshly_created_item(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        created = await create(client, AS_ALICE)

        body = await read(client, created["key"], AS_ALICE)

        assert "lastModifiedByUser" not in body["meta"]

    async def test_a_single_object_write_records_the_editor_too(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # PUT and PATCH take a different path through the route module from the
        # batch POST, and the desktop client uses all three.
        created = await create(client, AS_ALICE)
        key = created["key"]
        version = created["version"]

        response = await client.patch(
            f"/groups/100/items/{key}",
            headers=AS_BOB | JSON | {"If-Unmodified-Since-Version": str(version)},
            json={"title": "Two"},
        )
        assert response.status_code == 204, response.text

        body = await read(client, key, AS_ALICE)
        assert body["meta"]["lastModifiedByUser"]["username"] == "bob"

    async def test_a_replacing_write_records_the_editor_too(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        created = await create(client, AS_ALICE)
        key = created["key"]

        response = await client.put(
            f"/groups/100/items/{key}",
            headers=AS_BOB | JSON | {"If-Unmodified-Since-Version": str(created["version"])},
            json={"itemType": "book", "title": "Two", "version": created["version"]},
        )
        assert response.status_code == 204, response.text

        body = await read(client, key, AS_ALICE)
        assert body["meta"]["lastModifiedByUser"]["username"] == "bob"

    async def test_the_last_editor_replaces_the_previous_one(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        created = await create(client, AS_ALICE)
        after_bob = await client.post(
            "/groups/100/items",
            headers=AS_BOB | JSON,
            json=[{**created["data"], "title": "Two"}],
        )
        edited = after_bob.json()["successful"]["0"]["data"]

        await client.post(
            "/groups/100/items",
            headers=AS_ALICE | JSON,
            json=[{**edited, "title": "Three"}],
        )

        body = await read(client, created["key"], AS_ALICE)
        # Alice created it and last changed it, so it collapses to one name.
        assert body["meta"]["createdByUser"]["username"] == "alice"
        assert "lastModifiedByUser" not in body["meta"]


class TestNames:
    async def test_a_display_name_is_preferred(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        created = await create(client, AS_ALICE)

        body = await read(client, created["key"], AS_ALICE)

        assert body["meta"]["createdByUser"]["name"] == "Alice"

    async def test_an_account_with_no_display_name_falls_back_to_the_username(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        # `Zotero_Users::getName` returns the real name or the username.
        from sqlalchemy import update

        from altero.models import User

        await session.execute(update(User).where(User.id == 1).values(display_name=""))
        await session.commit()

        created = await create(client, AS_ALICE)
        body = await read(client, created["key"], AS_ALICE)

        assert body["meta"]["createdByUser"]["name"] == "alice"

    async def test_no_alternate_link_is_offered(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # Upstream links to the user's profile on zotero.org. altero does not
        # point clients at somebody else's copy of the data, which is the same
        # decision recorded for every other `alternate` link.
        created = await create(client, AS_ALICE)

        body = await read(client, created["key"], AS_ALICE)

        assert "links" not in body["meta"]["createdByUser"]
