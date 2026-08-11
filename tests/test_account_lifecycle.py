"""Making an account, taking one out of service, and removing one.

The three operations that used to need a shell on the server, and the reason
`docs/motivation.md` says an instance is something a systems administrator runs
rather than a librarian. Suspension is the sharp one: it has to refuse both
credentials, because a flag enforced in the browser and not in the v3 API would
leave every sync client of a suspended account working exactly as before.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import ApiKey, Group, Item, Library, LibraryType, PasswordReset, User
from altero.services import admin, passwordreset, webauth, websessions
from altero.services.auth import get_library
from tests.factories import make_group, make_item
from tests.test_web_routes import PASSWORD, csrf_headers, register


async def second_account(session: AsyncSession, username: str = "grace") -> User:
    """An ordinary account with a password, alongside the administrator.

    The administrator is made first where there is not one already, because
    the first account on an instance administers it -- and every refusal here
    about "the last administrator" would otherwise be about this account.
    """
    if await admin.count_administrators(session) == 0:
        await admin.create_user(session, username="ada")

    user = await admin.create_user(session, username=username)
    await webauth.set_password(session, user, PASSWORD)
    return user


class TestSuspension:
    async def test_an_api_key_stops_working(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The half that matters: a sync client must notice too."""
        await register(client)
        grace = await second_account(session)
        key = await admin.create_api_key(session, username="grace", name="laptop")

        await admin.set_disabled(session, grace, disabled=True)

        response = await client.get(f"/users/{grace.id}/items", headers={"Zotero-API-Key": key.key})
        assert response.status_code == 403

    async def test_the_browser_refuses_the_password(self, session: AsyncSession) -> None:
        grace = await second_account(session)
        await admin.set_disabled(session, grace, disabled=True)

        with pytest.raises(ForbiddenError):
            await webauth.login(session, username="grace", password=PASSWORD)

    async def test_a_session_already_open_stops_working(self, session: AsyncSession) -> None:
        """Suspending somebody who is signed in has to reach that browser too."""
        grace = await second_account(session)
        token, _ = await websessions.create(session, grace)

        await admin.set_disabled(session, grace, disabled=True)

        assert await websessions.lookup(session, token) is None

    async def test_the_library_is_untouched(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Access stops; the data stays. That is the whole point of suspending."""
        await register(client)
        grace = await second_account(session)
        library = await get_library(session, LibraryType.USER, grace.id)
        await make_item(session, library)

        await admin.set_disabled(session, grace, disabled=True)

        assert await session.scalar(select(Item).where(Item.library_id == library.id))

    async def test_reinstating_puts_everything_back(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await second_account(session)
        key = await admin.create_api_key(session, username="grace", name="laptop")
        await admin.set_disabled(session, grace, disabled=True)

        await admin.set_disabled(session, grace, disabled=False)

        response = await client.get(f"/users/{grace.id}/items", headers={"Zotero-API-Key": key.key})
        assert response.status_code == 200

    async def test_the_last_administrator_cannot_be_suspended(self, session: AsyncSession) -> None:
        """It would leave the instance with nobody able to reinstate them."""
        ada = await admin.create_user(session, username="ada")

        with pytest.raises(InvalidInputError, match="last administrator"):
            await admin.set_disabled(session, ada, disabled=True)


class TestRevokingCredentials:
    async def test_every_key_and_browser_goes(self, session: AsyncSession) -> None:
        """What you do when a laptop is lost, rather than when somebody leaves."""
        grace = await second_account(session)
        await admin.create_api_key(session, username="grace", name="laptop")
        token, _ = await websessions.create(session, grace)

        await admin.revoke_credentials(session, grace)

        assert not list(await session.scalars(select(ApiKey).where(ApiKey.user_id == grace.id)))
        assert await websessions.lookup(session, token) is None

    async def test_the_account_still_works(self, session: AsyncSession) -> None:
        grace = await second_account(session)

        await admin.revoke_credentials(session, grace)

        assert await webauth.login(session, username="grace", password=PASSWORD)


class TestDeletingAnAccount:
    async def test_the_account_and_its_library_go(self, session: AsyncSession) -> None:
        grace = await second_account(session)
        library = await get_library(session, LibraryType.USER, grace.id)
        await make_item(session, library)
        await admin.create_api_key(session, username="grace", name="laptop")

        await admin.delete_user(session, grace)

        assert await session.get(User, grace.id) is None
        assert await session.get(Library, library.id) is None
        assert not list(await session.scalars(select(Item)))

    async def test_an_account_owning_a_group_is_refused(self, session: AsyncSession) -> None:
        """Naming the groups rather than guessing an heir for them.

        Handing a group on is its own operation, with its own screen, and one
        the owner or an administrator of the group can already do.
        """
        grace = await second_account(session)
        await make_group(session, group_id=100, owner_id=grace.id, name="Engine")

        with pytest.raises(InvalidInputError, match="Engine"):
            await admin.delete_user(session, grace)

        assert await session.get(User, grace.id) is not None

    async def test_membership_of_somebody_else_s_group_is_not_an_obstacle(
        self, session: AsyncSession
    ) -> None:
        ada = await admin.create_user(session, username="ada")
        grace = await second_account(session)
        library = await make_group(session, group_id=100, owner_id=ada.id)
        await admin.add_group_member(session, library, username="grace")

        await admin.delete_user(session, grace)

        assert await session.get(User, grace.id) is None
        assert await session.get(Group, library.id) is not None

    async def test_the_last_administrator_cannot_be_deleted(self, session: AsyncSession) -> None:
        ada = await admin.create_user(session, username="ada")

        with pytest.raises(InvalidInputError, match="last administrator"):
            await admin.delete_user(session, ada)


class TestThroughTheBrowser:
    async def test_the_account_list_says_what_each_one_is(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        await second_account(session)

        body = (await client.get("/web/admin/users")).json()

        names = {entry["username"]: entry for entry in body["users"]}
        assert names["ada"]["administrator"] is True
        assert names["grace"]["disabled"] is False
        assert names["grace"]["keys"] == 0

    async def test_an_account_is_made_with_a_password_shown_once(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/web/auth/register",
            json={"username": "ada", "password": PASSWORD, "email": "ada@example.org"},
        )
        assert response.status_code == 201

        response = await client.post(
            "/web/admin/users",
            json={
                "username": "grace",
                "password": "another good password",
                "currentPassword": PASSWORD,
            },
            headers=csrf_headers(client),
        )

        assert response.status_code == 201
        assert response.json()["user"]["username"] == "grace"

    async def test_making_one_takes_the_administrator_s_own_password(
        self, client: httpx.AsyncClient
    ) -> None:
        """Everything that touches a credential does; see services/account.py."""
        await register(client)

        response = await client.post(
            "/web/admin/users",
            json={
                "username": "grace",
                "password": "another good password",
                "currentPassword": "not it",
            },
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_suspending_and_reinstating(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await second_account(session)

        suspended = await client.patch(
            f"/web/admin/users/{grace.id}",
            json={"disabled": True, "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        reinstated = await client.patch(
            f"/web/admin/users/{grace.id}",
            json={"disabled": False, "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert suspended.json()["user"]["disabled"] is True
        assert reinstated.json()["user"]["disabled"] is False

    async def test_an_administrator_cannot_suspend_themselves(
        self, client: httpx.AsyncClient
    ) -> None:
        """A door that locks from the inside with the key still in it."""
        await register(client)

        response = await client.patch(
            "/web/admin/users/1",
            json={"disabled": True, "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400
        assert "yourself" in response.json()["message"]

    async def test_deleting_an_account(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await second_account(session)
        # Read before the request: expiring the identity map afterwards would
        # make even reading the id a query in the wrong place.
        grace_id = grace.id

        response = await client.request(
            "DELETE",
            f"/web/admin/users/{grace_id}",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 204
        # The route ran in a session of its own; this one still holds its copy.
        session.expire_all()
        assert await session.get(User, grace_id) is None

    async def test_deleting_yourself_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.request(
            "DELETE",
            "/web/admin/users/1",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400

    async def test_revoking_somebody_s_credentials(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await second_account(session)
        await admin.create_api_key(session, username="grace", name="laptop")

        response = await client.post(
            f"/web/admin/users/{grace.id}/revoke",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert response.json()["keys"] == 1

    async def test_setting_somebody_s_password(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The other operation that sent people to a shell."""
        await register(client)
        grace = await second_account(session)

        response = await client.post(
            f"/web/admin/users/{grace.id}/password",
            json={"password": "a brand new password", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 204
        session.expire_all()
        assert await webauth.login(session, username="grace", password="a brand new password")

    async def test_a_suspended_account_cannot_use_its_cookie(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Suspension has to reach a browser that is already signed in."""
        await register(client)
        grace = await second_account(session)
        await client.post("/web/auth/login", json={"username": "grace", "password": PASSWORD})
        assert (await client.get("/web/auth/session")).status_code == 200

        await admin.set_disabled(session, grace, disabled=True)

        assert (await client.get("/web/auth/session")).status_code == 401


class TestAPasswordResetLink:
    """The alternative to typing somebody's password and telling them what it is.

    There is deliberately no self-service "I forgot my password" form: that
    turns an email address into a way in to an account, and needs a rate limit
    and a decision about how much the relay is trusted. Until then the person
    who runs the server does the resetting.
    """

    async def test_an_administrator_gets_a_link_to_hand_over(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Returned as well as mailed: most instances have no relay configured,
        and a link only readable in the server log would need the shell these
        screens exist to replace."""
        await register(client)
        grace = await second_account(session)

        response = await client.post(
            f"/web/admin/users/{grace.id}/reset",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert "/app/reset?token=" in response.json()["link"]

    async def test_the_link_says_whose_password_it_sets(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await second_account(session)
        token = await passwordreset.issue(session, grace)

        body = (await client.get(f"/web/auth/reset/{token}")).json()

        assert body["username"] == "grace"

    async def test_it_sets_the_password_without_a_session(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Followed in whatever browser is open; the token is the credential."""
        grace = await second_account(session)
        token = await passwordreset.issue(session, grace)
        client.cookies.clear()

        response = await client.post(
            "/web/auth/reset", json={"token": token, "password": "a password of my own"}
        )

        assert response.status_code == 200
        session.expire_all()
        assert await webauth.login(session, username="grace", password="a password of my own")

    async def test_a_link_works_once(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await second_account(session)
        token = await passwordreset.issue(session, grace)
        await client.post(
            "/web/auth/reset", json={"token": token, "password": "a password of my own"}
        )

        again = await client.post(
            "/web/auth/reset", json={"token": token, "password": "another one entirely"}
        )

        assert again.status_code == 403

    async def test_a_password_that_is_refused_does_not_spend_the_link(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Otherwise a typo costs somebody their only way in."""
        grace = await second_account(session)
        token = await passwordreset.issue(session, grace)

        refused = await client.post("/web/auth/reset", json={"token": token, "password": "short"})
        accepted = await client.post(
            "/web/auth/reset", json={"token": token, "password": "a password of my own"}
        )

        assert refused.status_code == 400
        assert accepted.status_code == 200

    async def test_issuing_a_second_link_stops_the_first(self, session: AsyncSession) -> None:
        grace = await second_account(session)
        first = await passwordreset.issue(session, grace)

        await passwordreset.issue(session, grace)

        with pytest.raises(ForbiddenError):
            await passwordreset.resolve(session, first)

    async def test_a_suspended_account_cannot_come_back_through_one(
        self, session: AsyncSession
    ) -> None:
        """A link issued before the suspension must not outlive it."""
        grace = await second_account(session)
        token = await passwordreset.issue(session, grace)

        await admin.set_disabled(session, grace, disabled=True)

        with pytest.raises(ForbiddenError):
            await passwordreset.resolve(session, token)

    async def test_an_expired_link_is_refused(self, session: AsyncSession) -> None:
        grace = await second_account(session)
        token = await passwordreset.issue(session, grace)
        outstanding = await session.scalar(select(PasswordReset))
        assert outstanding is not None
        outstanding.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        await session.commit()

        with pytest.raises(ForbiddenError):
            await passwordreset.resolve(session, token)

    async def test_nobody_but_an_administrator_can_issue_one(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await second_account(session)
        await client.post("/web/auth/login", json={"username": "grace", "password": PASSWORD})

        response = await client.post(
            f"/web/admin/users/{grace.id}/reset",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403


class TestNothingHalfMade:
    async def test_a_refused_password_leaves_no_account(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)

        response = await client.post(
            "/web/admin/users",
            json={"username": "grace", "password": "short", "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400
        assert await session.scalar(select(User).where(User.username == "grace")) is None

    async def test_an_address_somebody_else_holds_leaves_no_account(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)

        response = await client.post(
            "/web/admin/users",
            json={
                "username": "grace",
                "password": "a good password",
                "email": "ada@example.org",
                "currentPassword": PASSWORD,
            },
            headers=csrf_headers(client),
        )

        assert response.status_code == 400
        assert await session.scalar(select(User).where(User.username == "grace")) is None
