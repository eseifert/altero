"""Who administers the instance itself.

Permissions in altero are per library and stop there. This is the one flag that
is not: it says who may see what the instance costs, set retention and take an
account out of service. Nothing here grants access to anybody's library, and
tests/test_web_admin.py holds that line from the other side.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError
from altero.services import admin, webauth
from tests.test_web_routes import PASSWORD, register


class TestTheFirstAccount:
    async def test_it_administers_the_instance(self, session: AsyncSession) -> None:
        """Otherwise a fresh instance has an operator view nobody can open."""
        first = await admin.create_user(session, username="ada")

        assert first.administrator

    async def test_the_second_account_does_not(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="ada")

        second = await admin.create_user(session, username="grace")

        assert not second.administrator

    async def test_registering_in_the_browser_administers_it_too(
        self, session: AsyncSession
    ) -> None:
        """The rule is the account, not the way it was made.

        `altero user add` and the registration form both go through
        `create_user`, and an instance claimed through the browser would
        otherwise have no administrator at all.
        """
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )

        assert user.administrator


class TestGrantingIt:
    async def test_an_account_can_be_promoted(self, session: AsyncSession) -> None:
        await admin.create_user(session, username="ada")
        grace = await admin.create_user(session, username="grace")

        await admin.set_administrator(session, grace, administrator=True)

        assert grace.administrator

    async def test_an_account_can_be_demoted(self, session: AsyncSession) -> None:
        ada = await admin.create_user(session, username="ada")
        grace = await admin.create_user(session, username="grace")
        await admin.set_administrator(session, grace, administrator=True)

        await admin.set_administrator(session, ada, administrator=False)

        assert not ada.administrator

    async def test_the_last_administrator_cannot_be_demoted(self, session: AsyncSession) -> None:
        """An instance with no administrator has no way back but the shell.

        Which is the thing this whole layer exists to stop being necessary, so
        it must not be reachable by one careless click.
        """
        ada = await admin.create_user(session, username="ada")

        with pytest.raises(InvalidInputError, match="last administrator"):
            await admin.set_administrator(session, ada, administrator=False)

        assert ada.administrator

    async def test_demoting_someone_who_is_not_one_is_not_an_error(
        self, session: AsyncSession
    ) -> None:
        """It is the state that is asked for, not the change."""
        await admin.create_user(session, username="ada")
        grace = await admin.create_user(session, username="grace")

        await admin.set_administrator(session, grace, administrator=False)

        assert not grace.administrator


class TestWhatTheBrowserIsTold:
    async def test_the_session_reports_the_flag(self, client: httpx.AsyncClient) -> None:
        """The interface shows the administration screens from this alone."""
        await register(client)

        response = await client.get("/web/auth/session")

        assert response.json()["user"]["administrator"] is True

    async def test_another_account_is_told_it_is_not_one(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        await admin.create_user(session, username="grace")
        await webauth.set_password(
            session, await admin.get_user_by_name(session, "grace"), PASSWORD
        )

        await client.post("/web/auth/login", json={"username": "grace", "password": PASSWORD})
        response = await client.get("/web/auth/session")

        assert response.json()["user"]["administrator"] is False
