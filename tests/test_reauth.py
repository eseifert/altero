"""Proving again that the browser holds a credential of the account.

The point of this module is the account that has no password: one made by
`altero user add` and never given one, and -- once single sign-on exists -- one
an identity provider created. Before this seam existed, every credential-
touching operation asked for a password and so refused those accounts outright.
"""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import User
from altero.services import admin, reauth, webauth, websessions

PASSWORD = "correct horse battery staple"


async def make_user(session: AsyncSession) -> User:
    return await webauth.register(
        session, username="ada", password=PASSWORD, email="ada@example.org"
    )


async def make_passwordless_user(session: AsyncSession) -> User:
    """An account as `altero user add` leaves it: no password at all."""
    return await admin.create_user(session, username="grace", display_name="Grace")


class TestAPasswordIsStillProof:
    async def test_the_right_one_passes(self, session: AsyncSession) -> None:
        user = await make_user(session)
        _, record = await websessions.create(session, user)

        await reauth.require(session, user, record, password=PASSWORD)

    async def test_the_wrong_one_is_refused_with_the_message_it_always_gave(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)
        _, record = await websessions.create(session, user)

        with pytest.raises(ForbiddenError) as refusal:
            await reauth.require(session, user, record, password="not it")

        assert refusal.value.message == reauth.WRONG_PASSWORD

    async def test_the_right_one_stamps_the_session(self, session: AsyncSession) -> None:
        """Which is what lets a second operation follow without asking twice."""
        user = await make_user(session)
        _, record = await websessions.create(session, user)

        await reauth.require(session, user, record, password=PASSWORD)

        assert reauth.is_fresh(record)

    async def test_a_wrong_one_leaves_the_session_unproved(self, session: AsyncSession) -> None:
        user = await make_user(session)
        _, record = await websessions.create(session, user)

        with pytest.raises(ForbiddenError):
            await reauth.require(session, user, record, password="not it")

        assert not reauth.is_fresh(record)


class TestFreshness:
    async def test_a_recent_proof_stands_in_for_a_password(self, session: AsyncSession) -> None:
        user = await make_user(session)
        _, record = await websessions.create(session, user)
        await reauth.stamp(session, record)

        await reauth.require(session, user, record)

    async def test_an_old_proof_does_not(self, session: AsyncSession) -> None:
        user = await make_user(session)
        _, record = await websessions.create(session, user)
        await reauth.stamp(session, record)
        assert record.reauthenticated is not None
        record.reauthenticated -= reauth.FRESHNESS + timedelta(seconds=1)

        with pytest.raises(reauth.ReauthenticationRequired):
            await reauth.require(session, user, record)

    async def test_a_session_that_never_proved_anything_is_not_fresh(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)
        _, record = await websessions.create(session, user)

        assert not reauth.is_fresh(record)

    async def test_one_browser_proving_itself_says_nothing_about_another(
        self, session: AsyncSession
    ) -> None:
        """Two sessions are two claims to be this person, proved separately."""
        user = await make_user(session)
        _, here = await websessions.create(session, user)
        _, elsewhere = await websessions.create(session, user)

        await reauth.stamp(session, here)

        assert reauth.is_fresh(here)
        assert not reauth.is_fresh(elsewhere)


class TestAnAccountWithNoPassword:
    async def test_it_is_refused_when_nothing_has_been_proved(self, session: AsyncSession) -> None:
        user = await make_passwordless_user(session)
        _, record = await websessions.create(session, user)

        with pytest.raises(reauth.ReauthenticationRequired):
            await reauth.require(session, user, record)

    async def test_it_gets_through_on_a_recent_proof(self, session: AsyncSession) -> None:
        """The whole reason this seam exists: there is no password to ask for."""
        user = await make_passwordless_user(session)
        _, record = await websessions.create(session, user)
        await reauth.stamp(session, record)

        await reauth.require(session, user, record)

    async def test_an_empty_password_does_not_verify_against_a_missing_hash(
        self, session: AsyncSession
    ) -> None:
        """Otherwise a passwordless account is one empty string from takeover."""
        user = await make_passwordless_user(session)
        _, record = await websessions.create(session, user)

        with pytest.raises(reauth.ReauthenticationRequired):
            await reauth.require(session, user, record, password="")

    async def test_any_password_at_all_is_refused(self, session: AsyncSession) -> None:
        user = await make_passwordless_user(session)
        _, record = await websessions.create(session, user)

        with pytest.raises(ForbiddenError):
            await reauth.require(session, user, record, password="anything")

    async def test_the_refusal_says_which_of_the_two_is_missing(
        self, session: AsyncSession
    ) -> None:
        """An account with a password is told to give it; one without is not."""
        with_password = await make_user(session)
        without = await make_passwordless_user(session)
        _, one = await websessions.create(session, with_password)
        _, other = await websessions.create(session, without)

        with pytest.raises(reauth.ReauthenticationRequired) as asked:
            await reauth.require(session, with_password, one)
        with pytest.raises(reauth.ReauthenticationRequired) as confirmed:
            await reauth.require(session, without, other)

        assert "password" in asked.value.message
        assert "password" not in confirmed.value.message


class TestWithoutASession:
    async def test_a_password_still_works(self, session: AsyncSession) -> None:
        """The command line has no browser session and no need of one."""
        user = await make_user(session)

        await reauth.require(session, user, None, password=PASSWORD)

    async def test_nothing_at_all_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(reauth.ReauthenticationRequired):
            await reauth.require(session, user, None)
