"""The finer group roles: read-only, add-but-not-delete, own-items-only.

Asked for on the Zotero forums since 2010 ("Is it possible to add a new role
for group members"), answered upstream with "more fine-grained permissions have
long been on the agenda" and nothing shipped. altero has the enforcement point
already -- it enforces ``libraryReading``, ``libraryEditing`` and
``fileEditing`` rather than merely storing them -- so what these tests pin down
is the part that had to be decided rather than derived.

Three things they hold:

**The permission is a ceiling.** Never a grant. A member marked ``add`` in a
group that reserves editing for its administrators may still write nothing, and
a permission cannot widen what the key already allows.

**Read-only says itself in the client's own vocabulary.** ``libraryEditing``
renders as ``admins`` to that member and as whatever is stored to everybody
else, which is one library version with two representations -- settled by the
fact that ``GET /groups/<id>`` already answers 404 to a stranger and 200 to a
member, so the group resource was never requester-independent. The other two
permissions have no vocabulary and are enforcement only; the tests below check
that a client trying anyway is refused rather than quietly ignored.

**Trashing counts as removing.** It is how the desktop client deletes, so a
member who may not delete but may trash could still empty a library in one
gesture -- which is the thing the forum thread was posted after.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError
from altero.models import Library, MemberPermission, User
from altero.services import groups
from tests.factories import make_api_key, make_collection, make_group, make_item, make_user

ALICE = "AliceKeyAliceKeyAliceKey"
BOB = "BobKeyBobKeyBobKeyBobKey"

AS_ALICE = {"Zotero-API-Key": ALICE}
AS_BOB = {"Zotero-API-Key": BOB}
JSON = {"Content-Type": "application/json"}


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    """Alice owns a group; Bob is an ordinary member. Both keys reach groups."""
    for user_id, name, key in ((1, "alice", ALICE), (2, "bob", BOB)):
        await make_user(session, user_id=user_id, username=name, display_name=name.title())
        await make_api_key(
            session, key=key, user_id=user_id, all_groups_read=True, all_groups_write=True
        )
    return await make_group(session, group_id=100, owner_id=1, members={2: "member"})


async def restrict(session: AsyncSession, library: Library, permission: str) -> None:
    """Hold Bob to ``permission``."""
    bob = await session.get(User, 2)
    assert bob is not None
    await groups.set_permission(session, library, bob, permission)
    await session.commit()


async def add_item(
    client: httpx.AsyncClient, headers: dict[str, str], title: str = "One", **fields: object
) -> str:
    """Create one item and return its key."""
    response = await client.post(
        "/groups/100/items",
        headers=headers | JSON,
        json=[{"itemType": "book", "title": title, **fields}],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["successful"], body
    return str(body["successful"]["0"]["key"])


async def patch_item(
    client: httpx.AsyncClient, headers: dict[str, str], key: str, **fields: object
) -> httpx.Response:
    version = (await client.get(f"/groups/100/items/{key}", headers=headers)).json()["version"]
    return await client.patch(
        f"/groups/100/items/{key}",
        headers=headers | JSON | {"If-Unmodified-Since-Version": str(version)},
        json=dict(fields),
    )


async def delete_item(
    client: httpx.AsyncClient, headers: dict[str, str], key: str
) -> httpx.Response:
    version = (await client.get("/groups/100/items", headers=headers)).headers[
        "Last-Modified-Version"
    ]
    return await client.delete(
        f"/groups/100/items/{key}", headers=headers | {"If-Unmodified-Since-Version": version}
    )


class TestTheDefaultIsUnchanged:
    async def test_an_ordinary_member_writes_as_before(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        """Every existing membership is `inherit`, and nothing about it moved."""
        key = await add_item(client, AS_BOB)

        assert (await patch_item(client, AS_BOB, key, title="Two")).status_code == 204
        assert (await delete_item(client, AS_BOB, key)).status_code == 204

    async def test_the_group_reports_its_own_policy(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        body = (await client.get("/groups/100", headers=AS_BOB)).json()

        assert body["data"]["libraryEditing"] == "members"


class TestReadOnly:
    async def test_the_member_cannot_write(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.READ)

        response = await client.post(
            "/groups/100/items", headers=AS_BOB | JSON, json=[{"itemType": "book", "title": "One"}]
        )

        assert response.status_code == 403

    async def test_the_member_can_still_read(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.READ)

        response = await client.get("/groups/100/items", headers=AS_BOB)

        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_the_group_says_admins_to_that_member(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """The whole of how a read-only member is expressed to a sync client.

        The client draws a library read-only when `libraryEditing` is `admins`
        and it is not an administrator, and it needs to know nothing new.
        """
        await restrict(session, group, MemberPermission.READ)

        body = (await client.get("/groups/100", headers=AS_BOB)).json()

        assert body["data"]["libraryEditing"] == "admins"

    async def test_everybody_else_still_sees_the_stored_policy(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """Two representations of one library version, which is the decision.

        Held to be sound because the group resource was never
        requester-independent: a stranger gets 404 where a member gets 200, and
        `/users/<id>/groups` is by definition the caller's own list.
        """
        await restrict(session, group, MemberPermission.READ)

        body = (await client.get("/groups/100", headers=AS_ALICE)).json()

        assert body["data"]["libraryEditing"] == "members"

    async def test_the_members_own_group_list_says_admins_too(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """The list a client syncs from, which is where it matters most."""
        await restrict(session, group, MemberPermission.READ)

        listing = (await client.get("/users/2/groups", headers=AS_BOB)).json()

        assert [entry["data"]["libraryEditing"] for entry in listing] == ["admins"]

    async def test_files_are_refused_too(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        key = await add_item(
            client, AS_ALICE, itemType="attachment", linkMode="imported_file", title="File"
        )
        await restrict(session, group, MemberPermission.READ)

        response = await client.post(
            f"/groups/100/items/{key}/file",
            headers=AS_BOB,
            data={"md5": "0" * 32, "filename": "a.pdf", "filesize": "1", "mtime": "0"},
        )

        assert response.status_code == 403


class TestAddButNotRemove:
    async def test_the_member_can_add(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.ADD)

        assert await add_item(client, AS_BOB)

    async def test_the_member_can_change_anybodys_item(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """`add` is about removal, not about authorship."""
        key = await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.ADD)

        assert (await patch_item(client, AS_BOB, key, title="Two")).status_code == 204

    async def test_the_member_cannot_delete(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        key = await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.ADD)

        assert (await delete_item(client, AS_BOB, key)).status_code == 403

    async def test_the_member_cannot_delete_their_own_either(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """The point is the library, not ownership: `own` is the other one."""
        key = await add_item(client, AS_BOB)
        await restrict(session, group, MemberPermission.ADD)

        assert (await delete_item(client, AS_BOB, key)).status_code == 403

    async def test_the_member_cannot_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """Trashing is how the client deletes, so it is a removal here."""
        key = await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.ADD)

        response = await patch_item(client, AS_BOB, key, deleted=True)

        assert response.status_code == 403

    async def test_the_member_can_restore_from_the_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """Putting something back is not taking it away."""
        key = await add_item(client, AS_ALICE)
        assert (await patch_item(client, AS_ALICE, key, deleted=True)).status_code == 204
        await restrict(session, group, MemberPermission.ADD)

        assert (await patch_item(client, AS_BOB, key, deleted=False)).status_code == 204

    async def test_the_member_can_make_a_collection_and_not_delete_one(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.ADD)

        made = await client.post(
            "/groups/100/collections", headers=AS_BOB | JSON, json=[{"name": "Papers"}]
        )
        assert made.status_code == 200, made.text
        key = made.json()["successful"]["0"]["key"]

        version = made.headers["Last-Modified-Version"]
        removed = await client.delete(
            f"/groups/100/collections/{key}",
            headers=AS_BOB | {"If-Unmodified-Since-Version": version},
        )
        assert removed.status_code == 403

    async def test_the_member_cannot_delete_a_tag(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await add_item(client, AS_ALICE, tags=[{"tag": "physics"}])
        await restrict(session, group, MemberPermission.ADD)

        version = (await client.get("/groups/100/items", headers=AS_BOB)).headers[
            "Last-Modified-Version"
        ]
        response = await client.delete(
            "/groups/100/tags?tag=physics",
            headers=AS_BOB | {"If-Unmodified-Since-Version": version},
        )

        assert response.status_code == 403

    async def test_the_refusal_says_what_is_wrong(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """There is no client vocabulary for this, so the message is the whole
        explanation the person restricted is going to get."""
        key = await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.ADD)

        response = await delete_item(client, AS_BOB, key)

        assert "not remove" in response.text


class TestOwnItemsOnly:
    async def test_the_member_can_add(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.OWN)

        assert await add_item(client, AS_BOB)

    async def test_the_member_can_change_their_own(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.OWN)
        key = await add_item(client, AS_BOB)

        assert (await patch_item(client, AS_BOB, key, title="Two")).status_code == 204

    async def test_the_member_can_remove_their_own(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.OWN)
        key = await add_item(client, AS_BOB)

        assert (await delete_item(client, AS_BOB, key)).status_code == 204

    async def test_the_member_cannot_change_somebody_elses(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        key = await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.OWN)

        assert (await patch_item(client, AS_BOB, key, title="Two")).status_code == 403

    async def test_the_member_cannot_remove_somebody_elses(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        key = await add_item(client, AS_ALICE)
        await restrict(session, group, MemberPermission.OWN)

        assert (await delete_item(client, AS_BOB, key)).status_code == 403

    async def test_an_item_with_no_recorded_author_is_nobodys(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """The safe direction for a restriction is to hold.

        An item written before altero recorded authorship, or by a path that had
        no account to name, belongs to nobody -- and nobody is not this member.
        """
        item = await make_item(session, group, key="NOAUTHOR")
        await restrict(session, group, MemberPermission.OWN)

        assert (await patch_item(client, AS_BOB, item.key, title="Two")).status_code == 403

    async def test_the_shared_structure_is_read_only(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """Nothing records who made a collection, so none of them is theirs."""
        await restrict(session, group, MemberPermission.OWN)

        response = await client.post(
            "/groups/100/collections", headers=AS_BOB | JSON, json=[{"name": "Papers"}]
        )

        assert response.status_code == 200
        assert response.json()["failed"]["0"]["code"] == 403

    async def test_they_can_still_file_their_own_item(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """Filing is a write to the *item*, which is theirs."""
        collection = await make_collection(session, group, key="COLLONE1", name="Papers")
        await restrict(session, group, MemberPermission.OWN)
        key = await add_item(client, AS_BOB)

        response = await patch_item(client, AS_BOB, key, collections=[collection.key])

        assert response.status_code == 204


class TestItIsACeiling:
    async def test_the_groups_policy_still_wins(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """`add` in an admins-only group is not a way in."""
        alice = await session.get(User, 1)
        assert alice is not None
        stored = await groups.get_group(session, group)
        await groups.update_group(
            session, group, stored, {"libraryEditing": "admins"}, actor=alice, replace=False
        )
        await session.commit()
        await restrict(session, group, MemberPermission.ADD)

        response = await client.post(
            "/groups/100/items", headers=AS_BOB | JSON, json=[{"itemType": "book", "title": "One"}]
        )

        assert response.status_code == 403

    async def test_a_read_only_key_is_not_widened(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await make_api_key(
            session,
            key="ReadOnlyKeyReadOnlyKeyRO",
            user_id=2,
            all_groups_read=True,
            all_groups_write=False,
        )

        response = await client.post(
            "/groups/100/items",
            headers={"Zotero-API-Key": "ReadOnlyKeyReadOnlyKeyRO"} | JSON,
            json=[{"itemType": "book", "title": "One"}],
        )

        assert response.status_code == 403


class TestAdministrators:
    async def test_an_administrator_cannot_be_restricted(
        self, session: AsyncSession, group: Library
    ) -> None:
        """A restriction they could lift in a click is not a restriction."""
        alice = await session.get(User, 1)
        assert alice is not None

        with pytest.raises(InvalidInputError):
            await groups.set_permission(session, group, alice, MemberPermission.READ)

    async def test_promotion_clears_the_restriction(
        self, session: AsyncSession, group: Library
    ) -> None:
        bob = await session.get(User, 2)
        assert bob is not None
        await groups.set_permission(session, group, bob, MemberPermission.READ)

        member = await groups.set_role(session, group, bob, "admin")

        assert member.permission == MemberPermission.INHERIT

    async def test_the_v3_roster_reports_the_permission(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        await restrict(session, group, MemberPermission.ADD)

        roster = (await client.get("/groups/100/users", headers=AS_ALICE)).json()

        assert {entry["id"]: entry["permission"] for entry in roster} == {1: "inherit", 2: "add"}

    async def test_an_administrator_sets_one_over_the_v3_endpoint(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        response = await client.put(
            "/groups/100/users/2", headers=AS_ALICE | JSON, json={"permission": "read"}
        )

        assert response.status_code == 200
        assert response.json()["permission"] == "read"

    async def test_a_role_and_a_permission_can_be_sent_together(
        self, client: httpx.AsyncClient, session: AsyncSession, group: Library
    ) -> None:
        """Applied role first, so the promotion's reset does not eat the
        permission the same request asked for -- here, a demotion followed by a
        restriction."""
        await client.put("/groups/100/users/2", headers=AS_ALICE | JSON, json={"role": "admin"})

        response = await client.put(
            "/groups/100/users/2",
            headers=AS_ALICE | JSON,
            json={"role": "member", "permission": "own"},
        )

        assert response.json() == {
            "id": 2,
            "username": "bob",
            "displayName": "Bob",
            "role": "member",
            "permission": "own",
        }

    async def test_an_unknown_permission_is_refused(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        response = await client.put(
            "/groups/100/users/2", headers=AS_ALICE | JSON, json={"permission": "everything"}
        )

        assert response.status_code == 400
