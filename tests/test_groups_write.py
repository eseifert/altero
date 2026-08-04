"""Administering a group through the v3 API.

Upstream keeps all of this behind a superuser credential no API key can
present, so there is no reference implementation to compare against -- only the
shape of a group, which ``GET /groups/<id>`` publishes. What is asserted here
is therefore altero's own rule set, and the point of writing it down is that
the rules are the whole of the protection: a group is a library, and who may
restructure one is the same question as who may read it.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Collection, Group, GroupMember, Item, Library, LibraryType, Tag
from tests import factories

ALICE = "AliceKeyAliceKeyAliceKey"
BOB = "BobKeyBobKeyBobKeyBobKey"
CAROL = "CarolKeyCarolKeyCarolKey"

AS_ALICE = {"Zotero-API-Key": ALICE}
AS_BOB = {"Zotero-API-Key": BOB}
AS_CAROL = {"Zotero-API-Key": CAROL}

JSON = {"Content-Type": "application/json"}


@pytest.fixture
async def people(session: AsyncSession) -> None:
    """Three accounts, each with a key that reaches groups."""
    for user_id, name, key in ((1, "alice", ALICE), (2, "bob", BOB), (3, "carol", CAROL)):
        await factories.make_user(session, user_id=user_id, username=name, display_name=name)
        await factories.make_api_key(
            session, key=key, user_id=user_id, all_groups_read=True, all_groups_write=True
        )


async def make(client: httpx.AsyncClient, **payload: object) -> dict:
    payload.setdefault("name", "Kollaps")
    response = await client.post("/groups", json=payload, headers=AS_ALICE)
    assert response.status_code == 201, response.text
    return response.json()


class TestCreating:
    async def test_a_key_creates_a_group_owned_by_its_account(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client, description="A shared library")

        assert group["data"]["name"] == "Kollaps"
        assert group["data"]["owner"] == 1
        assert group["data"]["type"] == "Private"

    async def test_the_creator_becomes_its_administrator(
        self, people, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = await make(client)

        response = await client.get(f"/groups/{group['id']}/users", headers=AS_ALICE)

        assert response.json() == [
            {"id": 1, "username": "alice", "displayName": "alice", "role": "admin"}
        ]

    async def test_a_read_only_key_cannot_create_one(
        self, people, session: AsyncSession, client: httpx.AsyncClient
    ) -> None:
        """Creating a group is the account acting on its own data, and a
        read-only credential is not the account acting."""
        await factories.make_api_key(
            session, key="ReadOnlyReadOnlyReadOnly", user_id=1, library_write=False
        )

        response = await client.post(
            "/groups", json={"name": "No"}, headers={"Zotero-API-Key": "ReadOnlyReadOnlyReadOnly"}
        )

        assert response.status_code == 403

    async def test_an_anonymous_request_cannot_create_one(
        self, people, client: httpx.AsyncClient
    ) -> None:
        assert (await client.post("/groups", json={"name": "No"})).status_code == 403

    async def test_a_group_needs_a_name(self, people, client: httpx.AsyncClient) -> None:
        assert (await client.post("/groups", json={}, headers=AS_ALICE)).status_code == 400
        assert (
            await client.post("/groups", json={"name": "  "}, headers=AS_ALICE)
        ).status_code == 400

    async def test_a_property_out_of_range_is_refused(
        self, people, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/groups", json={"name": "x", "type": "Whatever"}, headers=AS_ALICE
        )

        assert response.status_code == 400
        assert "must be one of" in response.text

    async def test_a_property_that_does_not_exist_is_refused(
        self, people, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/groups", json={"name": "x", "colour": "teal"}, headers=AS_ALICE
        )

        assert response.status_code == 400

    async def test_a_key_cannot_create_a_group_in_somebody_elses_name(
        self, people, client: httpx.AsyncClient
    ) -> None:
        response = await client.post("/groups", json={"name": "x", "owner": 2}, headers=AS_ALICE)

        assert response.status_code == 400

    async def test_what_get_returns_can_be_sent_back(
        self, people, client: httpx.AsyncClient
    ) -> None:
        """The envelope round-trips, so a client need not unwrap it by hand."""
        group = await make(client, description="original")

        response = await client.put(f"/groups/{group['id']}", json=group, headers=AS_ALICE)

        assert response.status_code == 200
        assert response.json()["data"]["description"] == "original"


class TestMembership:
    async def test_a_stranger_cannot_read_a_private_group(
        self, people, client: httpx.AsyncClient
    ) -> None:
        """The hole this endpoint set found: a key granting "all groups" used to
        mean every group on the server rather than every group its owner is in,
        so anyone holding one could read every private library on the instance.
        """
        group = await make(client)

        assert (await client.get(f"/groups/{group['id']}", headers=AS_BOB)).status_code == 404
        assert (await client.get(f"/groups/{group['id']}/items", headers=AS_BOB)).status_code == 403

    async def test_a_member_reads_and_writes(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        assert (await client.get(f"/groups/{group['id']}", headers=AS_BOB)).status_code == 200
        written = await client.post(
            f"/groups/{group['id']}/items",
            json=[{"itemType": "book", "title": "Die Ausgewanderten"}],
            headers=AS_BOB,
        )
        assert written.json()["successful"]

    async def test_a_member_can_be_named_by_id(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)

        response = await client.post(
            f"/groups/{group['id']}/users", json={"userID": 2}, headers=AS_ALICE
        )

        assert response.status_code == 201
        assert response.json()["username"] == "bob"

    async def test_only_an_administrator_may_add_somebody(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        response = await client.post(
            f"/groups/{group['id']}/users", json={"username": "carol"}, headers=AS_BOB
        )

        assert response.status_code == 403

    async def test_adding_the_same_person_twice_is_refused(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        again = await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        assert again.status_code == 400

    async def test_a_role_can_be_changed(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        response = await client.put(
            f"/groups/{group['id']}/users/2", json={"role": "admin"}, headers=AS_ALICE
        )

        assert response.json()["role"] == "admin"

    async def test_the_owner_stays_an_administrator(
        self, people, client: httpx.AsyncClient
    ) -> None:
        """A group whose owner cannot administer it is one only a transfer
        should be able to produce."""
        group = await make(client)

        response = await client.put(
            f"/groups/{group['id']}/users/1", json={"role": "member"}, headers=AS_ALICE
        )

        assert response.status_code == 400

    async def test_the_owner_cannot_be_removed(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)

        response = await client.delete(f"/groups/{group['id']}/users/1", headers=AS_ALICE)

        assert response.status_code == 400

    async def test_anybody_may_remove_themselves(self, people, client: httpx.AsyncClient) -> None:
        """Leaving is not an administrative act. A member who had to ask is in
        a group they cannot get out of."""
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        left = await client.delete(f"/groups/{group['id']}/users/2", headers=AS_BOB)

        assert left.status_code == 204
        assert (await client.get(f"/groups/{group['id']}", headers=AS_BOB)).status_code == 404

    async def test_a_member_cannot_remove_another(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)
        for name in ("bob", "carol"):
            await client.post(
                f"/groups/{group['id']}/users", json={"username": name}, headers=AS_ALICE
            )

        response = await client.delete(f"/groups/{group['id']}/users/3", headers=AS_BOB)

        assert response.status_code == 403

    async def test_the_member_list_is_for_members(self, people, client: httpx.AsyncClient) -> None:
        """A public group publishes its contents, not the people who made it."""
        group = await make(client, type="PublicOpen", libraryReading="all")

        assert (await client.get(f"/groups/{group['id']}/items", headers=AS_BOB)).status_code == 200
        assert (await client.get(f"/groups/{group['id']}/users", headers=AS_BOB)).status_code == 404


class TestPolicy:
    async def test_editing_can_be_reserved_for_administrators(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client, libraryEditing="admins")
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        assert (await client.get(f"/groups/{group['id']}/items", headers=AS_BOB)).status_code == 200
        refused = await client.post(
            f"/groups/{group['id']}/items",
            json=[{"itemType": "book", "title": "x"}],
            headers=AS_BOB,
        )
        assert refused.status_code == 403

    async def test_file_uploads_have_a_policy_of_their_own(
        self, people, client: httpx.AsyncClient
    ) -> None:
        """A group can let members add items and still keep the attachments --
        which is where the disk goes -- to its administrators."""
        group = await make(client, fileEditing="admins")
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )
        created = await client.post(
            f"/groups/{group['id']}/items",
            json=[{"itemType": "attachment", "linkMode": "imported_file", "title": "x"}],
            headers=AS_BOB,
        )
        key = created.json()["successful"]["0"]["key"]

        response = await client.post(
            f"/groups/{group['id']}/items/{key}/file",
            data={
                "md5": "d41d8cd98f00b204e9800998ecf8427e",
                "filename": "x",
                "filesize": "0",
                "mtime": "0",
            },
            headers={**AS_BOB, "If-None-Match": "*"},
        )

        assert response.status_code == 403

    async def test_a_public_group_is_readable_by_anyone(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client, type="PublicOpen", libraryReading="all")

        assert (await client.get(f"/groups/{group['id']}/items")).status_code == 200

    async def test_a_public_group_is_still_not_writable_by_anyone(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client, type="PublicOpen", libraryReading="all")

        response = await client.post(
            f"/groups/{group['id']}/items",
            json=[{"itemType": "book", "title": "x"}],
            headers=AS_CAROL,
        )

        assert response.status_code == 403

    async def test_a_public_group_that_keeps_reading_to_members_is_private(
        self, people, client: httpx.AsyncClient
    ) -> None:
        """Both halves have to say so. Public as a page is not public as a
        library, and it is the library this server serves."""
        group = await make(client, type="PublicOpen", libraryReading="members")

        assert (await client.get(f"/groups/{group['id']}/items")).status_code == 403


class TestMetadata:
    async def test_put_resets_what_it_leaves_out(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client, type="PublicOpen", libraryReading="all", description="d")

        response = await client.put(
            f"/groups/{group['id']}", json={"name": "Kollaps"}, headers=AS_ALICE
        )

        assert response.json()["data"]["type"] == "Private"
        assert response.json()["data"]["description"] == ""

    async def test_patch_leaves_the_rest_alone(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client, type="PublicOpen", libraryReading="all")

        response = await client.patch(
            f"/groups/{group['id']}", json={"description": "changed"}, headers=AS_ALICE
        )

        assert response.json()["data"]["type"] == "PublicOpen"
        assert response.json()["data"]["description"] == "changed"

    async def test_a_rename_moves_the_library_name_too(
        self, people, client: httpx.AsyncClient
    ) -> None:
        """The library block of every object in the group reports the name, so
        a rename that moved only one of them would show two."""
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/items",
            json=[{"itemType": "book", "title": "x"}],
            headers=AS_ALICE,
        )

        await client.patch(f"/groups/{group['id']}", json={"name": "Renamed"}, headers=AS_ALICE)
        items = await client.get(f"/groups/{group['id']}/items", headers=AS_ALICE)

        assert items.json()[0]["library"]["name"] == "Renamed"

    async def test_a_write_moves_the_library_version(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client)

        response = await client.patch(
            f"/groups/{group['id']}", json={"description": "d"}, headers=AS_ALICE
        )

        assert response.json()["version"] == group["version"] + 1
        assert response.headers["Last-Modified-Version"] == str(group["version"] + 1)

    async def test_only_an_administrator_may_write(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        response = await client.patch(
            f"/groups/{group['id']}", json={"name": "Bobs"}, headers=AS_BOB
        )

        assert response.status_code == 403

    async def test_a_read_only_key_is_told_that_first(
        self, people, session: AsyncSession, client: httpx.AsyncClient
    ) -> None:
        """Being told "not an administrator" would be misleading to somebody
        who is one and is holding the wrong key."""
        group = await make(client)
        await factories.make_api_key(
            session, key="AliceReadsAliceReadsAlic", user_id=1, all_groups_read=True
        )

        response = await client.patch(
            f"/groups/{group['id']}",
            json={"name": "x"},
            headers={"Zotero-API-Key": "AliceReadsAliceReadsAlic"},
        )

        assert response.status_code == 403
        assert "may not write" in response.text


class TestOwnership:
    async def test_the_owner_can_hand_the_group_on(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        response = await client.patch(f"/groups/{group['id']}", json={"owner": 2}, headers=AS_ALICE)

        assert response.json()["data"]["owner"] == 2
        members = (await client.get(f"/groups/{group['id']}/users", headers=AS_BOB)).json()
        assert {entry["id"]: entry["role"] for entry in members}[2] == "admin"

    async def test_another_administrator_cannot(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users",
            json={"username": "bob", "role": "admin"},
            headers=AS_ALICE,
        )

        response = await client.patch(f"/groups/{group['id']}", json={"owner": 2}, headers=AS_BOB)

        assert response.status_code == 403

    async def test_it_cannot_be_handed_to_a_stranger(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client)

        response = await client.patch(f"/groups/{group['id']}", json={"owner": 3}, headers=AS_ALICE)

        assert response.status_code == 400


class TestDeleting:
    async def test_the_owner_deletes_it(self, people, client: httpx.AsyncClient) -> None:
        group = await make(client)

        assert (await client.delete(f"/groups/{group['id']}", headers=AS_ALICE)).status_code == 204
        assert (await client.get(f"/groups/{group['id']}", headers=AS_ALICE)).status_code == 404

    async def test_an_administrator_who_does_not_own_it_cannot(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users",
            json={"username": "bob", "role": "admin"},
            headers=AS_ALICE,
        )

        assert (await client.delete(f"/groups/{group['id']}", headers=AS_BOB)).status_code == 403

    async def test_everything_in_it_goes_too(
        self, people, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A row left pointing at a library that no longer exists is a foreign
        key that fails on the next backend that checks."""
        group = await make(client)
        library_id = await session.scalar(
            select(Library.id).where(
                Library.type == LibraryType.GROUP, Library.owner_id == group["id"]
            )
        )
        created = await client.post(
            f"/groups/{group['id']}/items",
            json=[{"itemType": "book", "title": "x", "tags": [{"tag": "read"}]}],
            headers=AS_ALICE,
        )
        assert created.json()["successful"]
        await client.post(
            f"/groups/{group['id']}/collections", json=[{"name": "Reading"}], headers=AS_ALICE
        )

        await client.delete(f"/groups/{group['id']}", headers=AS_ALICE)
        session.expire_all()

        for model in (Item, Collection, Tag, Group, GroupMember):
            column = model.library_id
            assert await session.scalar(select(column).where(column == library_id)) is None
        assert await session.get(Library, library_id) is None

    async def test_it_disappears_from_the_members_group_list(
        self, people, client: httpx.AsyncClient
    ) -> None:
        group = await make(client)
        await client.post(
            f"/groups/{group['id']}/users", json={"username": "bob"}, headers=AS_ALICE
        )

        await client.delete(f"/groups/{group['id']}", headers=AS_ALICE)

        assert (await client.get("/users/2/groups", headers=AS_BOB)).json() == []
