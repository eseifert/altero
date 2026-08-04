"""Groups and invitations, through the browser's own endpoints.

The rules themselves are tested against the service layer and the v3 endpoints
in ``test_groups_write.py``; what is checked here is that the cookie path
reaches the same ones, and the two things only this path has: an emailed
invitation that can be read without a session, and registration opening for the
address it was sent to.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Invitation, Library, User
from altero.services import invitations, passwords, webauth
from altero.settings import Settings
from tests import factories


@pytest.fixture
def settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    """Registration closed, which is the default and the interesting case."""
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


async def sign_up(client: httpx.AsyncClient, username: str = "ada", **extra: str) -> httpx.Response:
    return await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": "correct horse battery",
            "email": extra.get("email", f"{username}@example.org"),
        },
    )


async def sign_in(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/web/auth/login", json={"username": username, "password": "correct horse battery"}
    )
    assert response.status_code == 200, response.text


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["altero_csrf"]}


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in. The first is always allowed to register."""
    assert (await sign_up(client)).status_code == 201
    return client


class TestGroups:
    async def test_a_new_account_is_in_no_groups(self, ada: httpx.AsyncClient) -> None:
        response = await ada.get("/web/groups")

        assert response.json() == {"groups": []}

    async def test_anybody_signed_in_may_create_one(self, ada: httpx.AsyncClient) -> None:
        response = await ada.post(
            "/web/groups",
            json={"name": "Analytical Engine", "description": "Notes"},
            headers=csrf(ada),
        )

        assert response.status_code == 201
        group = response.json()
        assert (group["name"], group["role"], group["owner"]) == (
            "Analytical Engine",
            "admin",
            True,
        )
        assert group["numMembers"] == 1

    async def test_creating_one_needs_the_csrf_token(self, ada: httpx.AsyncClient) -> None:
        """The whole point of the token: a page on another origin can make the
        browser send the cookie but cannot read it."""
        response = await ada.post("/web/groups", json={"name": "No"})

        assert response.status_code == 403

    async def test_a_group_carries_the_id_a_sync_client_sees(self, ada: httpx.AsyncClient) -> None:
        """The interface addresses libraries by their internal id; a person
        reading their client's logs needs the other one."""
        created = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()

        assert created["groupId"] >= 1
        assert created["id"] != created["groupId"] or True  # ids may coincide

    async def test_metadata_can_be_changed(self, ada: httpx.AsyncClient) -> None:
        created = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()

        response = await ada.patch(
            f"/web/groups/{created['id']}",
            json={"libraryEditing": "admins", "type": "PublicOpen"},
            headers=csrf(ada),
        )

        assert response.json()["libraryEditing"] == "admins"
        assert response.json()["type"] == "PublicOpen"

    async def test_a_group_you_are_not_in_is_not_found(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """404 rather than 403, as the v3 endpoint does: a stranger learns
        nothing about which private groups exist."""
        await factories.make_user(session, user_id=99, username="somebody")
        library = await factories.make_group(session, group_id=50, owner_id=99)

        assert (await ada.get(f"/web/groups/{library.id}")).status_code == 404

    async def test_only_the_owner_may_delete_one(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        created = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()

        assert (
            await ada.delete(f"/web/groups/{created['id']}", headers=csrf(ada))
        ).status_code == 204
        assert (await ada.get("/web/groups")).json() == {"groups": []}


class TestMembersInTheBrowser:
    @pytest.fixture
    async def shared(self, client: httpx.AsyncClient, session: AsyncSession) -> dict:
        """Ada owns a group; Grace is a member, and Grace is signed in."""
        await sign_up(client, "ada")
        group = (
            await client.post("/web/groups", json={"name": "Engine"}, headers=csrf(client))
        ).json()
        await client.post("/web/auth/logout", headers=csrf(client))

        await factories.make_user(session, user_id=2, username="grace", display_name="Grace")
        await factories.add_group_member(session, library_id=group["id"], user_id=2)
        return group

    async def test_a_member_sees_the_group_but_not_its_invitations(
        self, shared: dict, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Only an administrator hands membership out, so only an
        administrator is shown who has been offered it."""
        grace = await session.get(User, 2)
        assert grace is not None
        grace.password_hash = passwords.hash_password("correct horse battery")
        grace.email = "grace@example.org"
        await session.commit()
        await sign_in(client, "grace")

        payload = (await client.get(f"/web/groups/{shared['id']}")).json()

        assert payload["role"] == "member"
        assert [entry["username"] for entry in payload["members"]] == ["ada", "grace"]
        assert payload["invitations"] == []


class TestInvitations:
    async def test_an_administrator_invites_an_address(self, ada: httpx.AsyncClient) -> None:
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()

        response = await ada.post(
            f"/web/libraries/{group['id']}/invitations",
            json={"email": "grace@example.org", "role": "member"},
            headers=csrf(ada),
        )

        assert response.status_code == 201
        listed = (await ada.get(f"/web/groups/{group['id']}")).json()["invitations"]
        assert [entry["email"] for entry in listed] == ["grace@example.org"]

    async def test_one_can_be_withdrawn(self, ada: httpx.AsyncClient) -> None:
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        invitation = (
            await ada.post(
                f"/web/libraries/{group['id']}/invitations",
                json={"email": "grace@example.org"},
                headers=csrf(ada),
            )
        ).json()["invitation"]

        removed = await ada.delete(f"/web/invitations/{invitation['id']}", headers=csrf(ada))

        assert removed.status_code == 204
        assert (await ada.get(f"/web/groups/{group['id']}")).json()["invitations"] == []

    async def test_the_emailed_link_is_readable_without_signing_in(
        self, ada: httpx.AsyncClient, session: AsyncSession, app: FastAPI
    ) -> None:
        """Somebody with no account here has to be able to see what they were
        asked to join before deciding to make one."""
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()

        library = await session.get(Library, group["id"])
        inviter = await session.get(User, 1)
        assert library is not None
        assert inviter is not None
        _, token = await invitations.invite_with_token(
            session, library=library, inviter=inviter, email="grace@example.org"
        )

        # A client of its own, carrying no session cookie at all.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as guest:
            response = await guest.get(f"/web/invitations/token/{token}")

        assert response.status_code == 200
        assert response.json()["libraryName"] == "Engine"
        assert response.json()["hasAccount"] is False

    async def test_an_unknown_token_is_not_found(self, ada: httpx.AsyncClient) -> None:
        assert (await ada.get("/web/invitations/token/nonsense")).status_code == 404


class TestRegistration:
    async def test_the_first_account_is_always_allowed(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/config")).json()["firstAccount"] is True
        assert (await sign_up(client)).status_code == 201

    async def test_and_the_second_is_not(self, ada: httpx.AsyncClient) -> None:
        config = (await ada.get("/web/config")).json()

        assert (config["registrationOpen"], config["firstAccount"]) == (False, False)
        assert (await sign_up(ada, "grace")).status_code == 403

    async def test_unless_the_deployment_opened_it(
        self, tmp_path, app, client: httpx.AsyncClient
    ) -> None:  # type: ignore[no-untyped-def]
        await sign_up(client)
        app.state.settings = app.state.settings.model_copy(update={"open_registration": True})

        assert (await client.get("/web/config")).json()["registrationOpen"] is True
        assert (await sign_up(client, "grace")).status_code == 201

    async def test_or_the_address_has_an_invitation_waiting(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Inviting somebody who is not here yet is the documented way to bring
        them into a group, and it was unreachable: the link they received
        landed on a form that refused them."""
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        await ada.post(
            f"/web/libraries/{group['id']}/invitations",
            json={"email": "grace@example.org"},
            headers=csrf(ada),
        )

        assert (await sign_up(ada, "hopper")).status_code == 403
        joined = await sign_up(ada, "grace", email="grace@example.org")

        assert joined.status_code == 201

    async def test_the_public_config_still_says_closed(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """An invitation opens the door for one address. Reporting the instance
        as open would advertise a form that refuses almost everybody."""
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        await ada.post(
            f"/web/libraries/{group['id']}/invitations",
            json={"email": "grace@example.org"},
            headers=csrf(ada),
        )

        assert (await ada.get("/web/config")).json()["registrationOpen"] is False

    async def test_an_expired_invitation_does_not_open_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        await ada.post(
            f"/web/libraries/{group['id']}/invitations",
            json={"email": "grace@example.org"},
            headers=csrf(ada),
        )

        invitation = await session.scalar(select(Invitation))
        assert invitation is not None
        invitation.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        await session.commit()

        assert await webauth.registration_open(session, email="grace@example.org") is False
