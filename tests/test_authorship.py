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


class TestSorting:
    """`sort=addedBy`, and `editedBy` which upstream has not built.

    `addedBy` is upstream's and carries a quirk worth copying: it sorts by the
    author's *name*, and where there is no authorship to sort by -- a personal
    library, or a group where nothing has been written since this existed -- it
    silently falls back to `dateAdded` rather than erroring or ordering
    arbitrarily. `Zotero_Items::search` does that with an `if ($isGroup &&
    $createdByUserIDs)`.
    """

    @pytest.fixture
    async def three(self, client: httpx.AsyncClient, group: Library) -> None:
        """Three items whose key order is the reverse of their author order.

        Deliberate: the sort this replaces fell through to an empty key and so
        ordered by item key, and with generated keys these assertions would
        have passed against it a third of the time. Bob's item sorts first by
        key and last by name, so the two orders cannot be confused.
        """
        await create(client, AS_BOB, key="AAAA2345", title="Bob's")
        await create(client, AS_ALICE, key="BBBB2345", title="Alice's first")
        await create(client, AS_ALICE, key="CCCC2345", title="Alice's second")

    async def test_added_by_orders_by_the_authors_name(
        self, client: httpx.AsyncClient, three: None
    ) -> None:
        listing = (await client.get("/groups/100/items?sort=addedBy", headers=AS_ALICE)).json()

        who = [item["meta"]["createdByUser"]["name"] for item in listing]
        assert who == ["Alice", "Alice", "Bob"]

    async def test_it_can_be_reversed(self, client: httpx.AsyncClient, three: None) -> None:
        listing = (
            await client.get("/groups/100/items?sort=addedBy&direction=desc", headers=AS_ALICE)
        ).json()

        who = [item["meta"]["createdByUser"]["name"] for item in listing]
        assert who == ["Bob", "Alice", "Alice"]

    async def test_edited_by_orders_by_whoever_last_touched_it(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # Not upstream's: dataserver#153 asks for this and it has never been
        # built. Recorded as a divergence in docs/compatibility.md.
        alices = await create(client, AS_ALICE, title="Alice's")
        bobs = await create(client, AS_ALICE, title="To be Bob's")
        await client.post(
            "/groups/100/items", headers=AS_BOB | JSON, json=[{**bobs["data"], "title": "Bob's"}]
        )

        listing = (await client.get("/groups/100/items?sort=editedBy", headers=AS_ALICE)).json()

        assert [item["key"] for item in listing] == [alices["key"], bobs["key"]]

    async def test_a_personal_library_falls_back_to_date_added(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # Upstream's fallback, and the reason it exists: nothing in a personal
        # library has an author to sort by, so the parameter has to mean
        # something rather than fail.
        #
        # Compared against `direction=asc` rather than a bare `dateAdded`,
        # because the default direction is decided by the name of the sort and
        # not by what it falls back to: anything beginning with `date` counts
        # down and everything else counts up, so `addedBy` ascends even when it
        # is ordering by `dateAdded` underneath. That asymmetry is upstream's,
        # in `getDefaultDirection`.
        for title in ("One", "Two"):
            await client.post(
                "/users/1/items",
                headers=AS_ALICE | JSON,
                json=[{"itemType": "book", "title": title}],
            )

        by_author = await client.get("/users/1/items?sort=addedBy", headers=AS_ALICE)
        by_date = await client.get("/users/1/items?sort=dateAdded&direction=asc", headers=AS_ALICE)

        assert by_author.status_code == 200
        assert [item["key"] for item in by_author.json()] == [
            item["key"] for item in by_date.json()
        ]

    async def test_a_group_with_no_authorship_recorded_falls_back_too(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        # Items that predate the columns, which is every item in every library
        # that upgraded into this.
        from tests.factories import make_item

        await make_item(session, group, key="OLDER2345", fields={"title": "Older"})
        await make_item(session, group, key="OLDEST234", fields={"title": "Oldest"})

        response = await client.get("/groups/100/items?sort=addedBy", headers=AS_ALICE)

        assert response.status_code == 200
        assert len(response.json()) == 2


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
