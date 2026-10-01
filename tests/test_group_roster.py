"""What the desktop client concludes from a group's JSON.

``Zotero.Groups.getPermissionsFromJSON`` in the client's
``chrome/content/zotero/xpcom/data/groups.js`` decides whether a group library
is editable, and it reads ``libraryEditing`` only for somebody it has already
found in ``members``. An account in neither ``admins`` nor ``members`` is not
the owner's equal and not a member either: it gets a read-only library whatever
the group's policy says. The dataserver's ``Zotero_Group::toJSON`` writes both
arrays, which is why upstream never shows the problem.

So these tests assert what the client *decides*, through a port of that
function, rather than the shape of the JSON alone -- the shape is what the old
tests checked, and they passed while every member of every group but its owner
synced a read-only library. Found by @alpichlabs in PR #14.
"""

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, MemberPermission, User
from altero.services import admin, groups, invitations
from tests.factories import make_api_key, make_group, make_user
from tests.test_query_counts import capture_sql

ALICE = "AliceKeyAliceKeyAliceKey"
BOB = "BobKeyBobKeyBobKeyBobKey"
CAROL = "CarolKeyCarolKeyCarolKey"

AS_ALICE = {"Zotero-API-Key": ALICE}
AS_BOB = {"Zotero-API-Key": BOB}
AS_CAROL = {"Zotero-API-Key": CAROL}

#: The two ways a client reads a group: the listing every sync starts from, and
#: the single group it fetches when the listing's version has moved.
SOURCES = ("/groups/100", "/users/2/groups")


def client_permissions(data: dict, user_id: int) -> tuple[bool, bool]:
    """``Zotero.Groups.getPermissionsFromJSON``, branch for branch.

    Returns ``(editable, filesEditable)``. ``json.admins &&`` and
    ``json.members &&`` in the original are why a missing array is no error and
    no membership either.
    """
    if data["owner"] == user_id or user_id in data.get("admins", []):
        return True, data["fileEditing"] != "none"
    if user_id in data.get("members", []) and data["libraryEditing"] == "members":
        return True, data["fileEditing"] == "members"
    return False, False


async def bobs_view(client: httpx.AsyncClient, source: str) -> dict:
    response = await client.get(source, headers=AS_BOB)
    assert response.status_code == 200, response.text
    body = response.json()
    return (body[0] if isinstance(body, list) else body)["data"]


@pytest.fixture
async def people(session: AsyncSession) -> None:
    """Alice, Bob and Carol, each with a key that reaches groups."""
    for user_id, name, key in ((1, "alice", ALICE), (2, "bob", BOB), (3, "carol", CAROL)):
        await make_user(session, user_id=user_id, username=name, display_name=name.title())
        await make_api_key(
            session, key=key, user_id=user_id, all_groups_read=True, all_groups_write=True
        )


async def set_policy(session: AsyncSession, library: Library, **values: str) -> None:
    group = await groups.get_group(session, library)
    for name, value in values.items():
        setattr(group, name, value)
    await session.commit()


@pytest.mark.parametrize("source", SOURCES)
class TestWhatTheClientDecides:
    async def test_a_member_may_edit_a_group_open_to_its_members(
        self, people, session: AsyncSession, client: httpx.AsyncClient, source: str
    ) -> None:
        """The ordinary case, and the one that was broken."""
        await make_group(session, owner_id=1, members={2: "member"})

        assert client_permissions(await bobs_view(client, source), 2) == (True, True)

    async def test_an_administrator_may_edit_a_group_reserved_to_administrators(
        self, people, session: AsyncSession, client: httpx.AsyncClient, source: str
    ) -> None:
        library = await make_group(session, owner_id=1, members={2: "admin"})
        await set_policy(session, library, library_editing="admins", file_editing="admins")

        assert client_permissions(await bobs_view(client, source), 2) == (True, True)

    async def test_a_member_may_not_edit_a_group_reserved_to_administrators(
        self, people, session: AsyncSession, client: httpx.AsyncClient, source: str
    ) -> None:
        library = await make_group(session, owner_id=1, members={2: "member"})
        await set_policy(session, library, library_editing="admins")

        assert client_permissions(await bobs_view(client, source), 2) == (False, False)

    async def test_a_member_may_edit_but_not_upload_where_files_are_reserved(
        self, people, session: AsyncSession, client: httpx.AsyncClient, source: str
    ) -> None:
        library = await make_group(session, owner_id=1, members={2: "member"})
        await set_policy(session, library, file_editing="admins")

        assert client_permissions(await bobs_view(client, source), 2) == (True, False)

    async def test_a_member_held_to_reading_may_not_edit(
        self, people, session: AsyncSession, client: httpx.AsyncClient, source: str
    ) -> None:
        """The per-member restriction, said through ``libraryEditing``.

        It reaches the client only because the member is found in ``members``
        first: ``libraryEditing`` is never read for anybody else.
        """
        library = await make_group(session, owner_id=1, members={2: "member"})
        bob = await session.get(User, 2)
        assert bob is not None
        await groups.set_permission(session, library, bob, MemberPermission.READ.value)
        await session.commit()

        assert client_permissions(await bobs_view(client, source), 2) == (False, False)


class TestTheRoster:
    async def test_the_owner_is_not_listed_among_the_administrators(
        self, people, session: AsyncSession, client: httpx.AsyncClient
    ) -> None:
        """altero stores the owner as an admin; upstream as a role of its own.

        ``getAdmins`` selects ``role='admin'``, which upstream's owner does not
        hold, so the owner appears as ``owner`` and nowhere else.
        """
        await make_group(session, owner_id=1, members={2: "admin", 3: "member"})

        data = (await client.get("/groups/100", headers=AS_ALICE)).json()["data"]

        assert (data["owner"], data["admins"], data["members"]) == (1, [2], [3])

    async def test_an_empty_role_is_left_out(
        self, people, session: AsyncSession, client: httpx.AsyncClient
    ) -> None:
        """``toJSON`` writes each array only ``if ($admins)``."""
        await make_group(session, owner_id=1)

        data = (await client.get("/groups/100", headers=AS_ALICE)).json()["data"]

        assert "admins" not in data
        assert "members" not in data

    @pytest.mark.parametrize("headers", [{}, AS_CAROL], ids=["anonymous", "stranger"])
    async def test_somebody_outside_a_public_group_is_not_told_who_is_in_it(
        self, people, session: AsyncSession, client: httpx.AsyncClient, headers: dict
    ) -> None:
        """altero's decision, not upstream's, which hands anyone the ids.

        Nobody outside a group syncs it -- the client syncs the groups in its
        own ``/users/<id>/groups`` -- so the arrays would serve only to tell a
        stranger which accounts belong to it.
        """
        await make_user(session, user_id=4, username="dave")
        library = await make_group(
            session, owner_id=1, public=True, members={2: "admin", 4: "member"}
        )
        await set_policy(session, library, type="PublicOpen", library_reading="all")

        response = await client.get("/groups/100", headers=headers)

        assert response.status_code == 200
        assert "admins" not in response.json()["data"]
        assert "members" not in response.json()["data"]

    async def test_what_was_read_can_be_written_back(
        self, people, session: AsyncSession, client: httpx.AsyncClient
    ) -> None:
        """The roster is reported, never written through the group's metadata."""
        await make_group(session, owner_id=1, members={2: "member"})
        data = (await client.get("/groups/100", headers=AS_ALICE)).json()["data"]

        response = await client.put(
            "/groups/100", json=data | {"members": [3], "admins": [2]}, headers=AS_ALICE
        )

        assert response.status_code == 200, response.text
        assert (response.json()["data"].get("admins"), response.json()["data"]["members"]) == (
            None,
            [2],
        )

    async def test_listing_more_groups_costs_no_more_queries(
        self, people, session: AsyncSession, client: httpx.AsyncClient, app: FastAPI
    ) -> None:
        """Every sync starts with this listing, so the rosters come in one go."""
        await make_group(session, group_id=100, owner_id=1, members={2: "member"})
        with capture_sql(app) as one:
            await client.get("/users/2/groups", headers=AS_BOB)

        for group_id in (101, 102, 103):
            await make_group(session, group_id=group_id, owner_id=1, members={2: "member"})
        with capture_sql(app) as four:
            listing = (await client.get("/users/2/groups", headers=AS_BOB)).json()

        assert [entry["data"]["members"] for entry in listing] == [[2]] * 4
        assert len(four) == len(one)


class TestTheVersionMoves:
    """A client fetches a group again only when its version has moved.

    ``syncRunner.js`` compares the versions in ``/users/<id>/groups?format=versions``
    with its own and asks for the rest by id, so a change of role that leaves the
    version alone is a change the client never sees. The v3 and browser routes
    already move it; these are the two other ways a membership changes.
    """

    async def version(self, session: AsyncSession, library: Library) -> int:
        return await session.scalar(select(Library.version).where(Library.id == library.id)) or 0

    @pytest.mark.parametrize(
        "change",
        [
            lambda session, library: admin.add_group_member(session, library, username="carol"),
            lambda session, library: admin.set_group_member_role(
                session, library, username="bob", role="admin"
            ),
            lambda session, library: admin.set_group_member_permission(
                session, library, username="bob", permission="read"
            ),
            lambda session, library: admin.remove_group_member(session, library, username="bob"),
        ],
        ids=["add", "role", "permission", "remove"],
    )
    async def test_on_the_command_line(self, people, session: AsyncSession, change) -> None:
        library = await make_group(session, owner_id=1, members={2: "member"})
        before = await self.version(session, library)

        await change(session, library)

        assert await self.version(session, library) == before + 1

    async def test_when_an_invitation_is_accepted(self, people, session: AsyncSession) -> None:
        library = await make_group(session, owner_id=1)
        alice = await session.get(User, 1)
        carol = await session.get(User, 3)
        assert alice is not None
        assert carol is not None
        carol.email = "carol@example.org"
        await session.commit()
        invitation = await invitations.invite(
            session, library=library, inviter=alice, email="carol@example.org"
        )
        before = await self.version(session, library)

        await invitations.accept(session, invitation, carol)

        assert await self.version(session, library) == before + 1
