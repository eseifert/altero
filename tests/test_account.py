"""Changes a person makes to their own account.

The recurring rule here is re-authentication. A session cookie is exactly what
an attacker who borrowed an unlocked laptop already holds, so anything that
alters a credential asks for the current password first; without that, each of
these is a one-request takeover.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import User
from altero.services import account, emailverify, passwords, totp, webauth, websessions

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a quite different long password"


async def make_user(session: AsyncSession) -> User:
    return await webauth.register(
        session, username="ada", password=PASSWORD, email="ada@example.org"
    )


def _now() -> int:
    from datetime import UTC, datetime

    return int(datetime.now(UTC).timestamp())


class TestDisplayName:
    async def test_it_can_be_changed_without_a_password(self, session: AsyncSession) -> None:
        """It is not a credential, and should not feel like one."""
        user = await make_user(session)

        await account.set_display_name(session, user, "Ada Lovelace")

        assert user.display_name == "Ada Lovelace"

    async def test_it_is_trimmed(self, session: AsyncSession) -> None:
        user = await make_user(session)

        await account.set_display_name(session, user, "  Ada  ")

        assert user.display_name == "Ada"

    async def test_an_absurd_one_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.set_display_name(session, user, "a" * 300)


class TestChangingThePassword:
    async def test_the_current_password_is_required(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(ForbiddenError):
            await account.change_password(
                session, user, current_password="wrong", new_password=NEW_PASSWORD
            )

        assert passwords.verify_password(user.password_hash, PASSWORD) is True

    async def test_the_right_one_replaces_it(self, session: AsyncSession) -> None:
        user = await make_user(session)

        await account.change_password(
            session, user, current_password=PASSWORD, new_password=NEW_PASSWORD
        )

        assert passwords.verify_password(user.password_hash, NEW_PASSWORD) is True

    async def test_a_short_new_password_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.change_password(
                session, user, current_password=PASSWORD, new_password="short"
            )

    async def test_reusing_the_same_password_is_refused(self, session: AsyncSession) -> None:
        """It would sign every other session out for no gain."""
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.change_password(
                session, user, current_password=PASSWORD, new_password=PASSWORD
            )

    async def test_other_sessions_end_and_this_one_survives(self, session: AsyncSession) -> None:
        user = await make_user(session)
        elsewhere, _ = await websessions.create(session, user)
        here_token, here = await websessions.create(session, user)

        await account.change_password(
            session,
            user,
            current_password=PASSWORD,
            new_password=NEW_PASSWORD,
            keep=here,
        )

        assert await websessions.lookup(session, elsewhere) is None
        assert await websessions.lookup(session, here_token) is not None


class TestChangingTheAddress:
    async def test_the_current_password_is_required(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(ForbiddenError):
            await account.request_email_change(
                session, user, new_email="new@example.org", current_password="wrong"
            )

    async def test_the_address_does_not_change_until_the_link_is_followed(
        self, session: AsyncSession
    ) -> None:
        """A typo must not take the security notices with it."""
        user = await make_user(session)

        token = await account.request_email_change(
            session, user, new_email="new@example.org", current_password=PASSWORD
        )

        assert user.email == "ada@example.org"

        await emailverify.confirm(session, token)

        assert user.email == "new@example.org"

    async def test_an_address_somebody_else_holds_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )

        with pytest.raises(InvalidInputError):
            await account.request_email_change(
                session, user, new_email="grace@example.org", current_password=PASSWORD
            )

    async def test_the_address_already_held_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.request_email_change(
                session, user, new_email="ada@example.org", current_password=PASSWORD
            )

    async def test_something_that_is_not_an_address_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.request_email_change(
                session, user, new_email="nonsense", current_password=PASSWORD
            )


class TestEnrollingAnAuthenticator:
    async def test_starting_does_not_yet_require_a_code_to_sign_in(
        self, session: AsyncSession
    ) -> None:
        """An interrupted setup must not lock the account."""
        user = await make_user(session)

        await account.begin_totp_enrolment(session, user)

        result = await webauth.login(session, username="ada", password=PASSWORD)
        assert result.needs_factor is None
        assert await account.is_totp_active(session, user) is False

    async def test_it_returns_a_secret_and_a_uri_an_app_can_scan(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)

        enrolment = await account.begin_totp_enrolment(session, user)

        assert enrolment.uri.startswith("otpauth://totp/altero:ada?")
        assert enrolment.secret in enrolment.uri

    async def test_confirming_with_a_real_code_turns_it_on(self, session: AsyncSession) -> None:
        user = await make_user(session)
        enrolment = await account.begin_totp_enrolment(session, user)

        await account.confirm_totp_enrolment(session, user, totp.code_at(enrolment.secret, _now()))

        assert await account.is_totp_active(session, user) is True
        result = await webauth.login(session, username="ada", password=PASSWORD)
        assert result.needs_factor == "totp"

    async def test_a_wrong_code_leaves_it_off(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await account.begin_totp_enrolment(session, user)

        with pytest.raises(ForbiddenError):
            await account.confirm_totp_enrolment(session, user, "000000")

        assert await account.is_totp_active(session, user) is False

    async def test_confirming_without_starting_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.confirm_totp_enrolment(session, user, "000000")

    async def test_starting_again_replaces_an_unproved_secret(self, session: AsyncSession) -> None:
        user = await make_user(session)
        first = await account.begin_totp_enrolment(session, user)

        second = await account.begin_totp_enrolment(session, user)

        assert second.secret != first.secret
        with pytest.raises(ForbiddenError):
            await account.confirm_totp_enrolment(session, user, totp.code_at(first.secret, _now()))

    async def test_starting_again_once_it_is_on_is_refused(self, session: AsyncSession) -> None:
        """Otherwise the working factor is silently replaced by an unproved one."""
        user = await make_user(session)
        enrolment = await account.begin_totp_enrolment(session, user)
        await account.confirm_totp_enrolment(session, user, totp.code_at(enrolment.secret, _now()))

        with pytest.raises(InvalidInputError):
            await account.begin_totp_enrolment(session, user)

        assert await account.is_totp_active(session, user) is True


class TestRemovingAnAuthenticator:
    async def test_it_needs_the_password(self, session: AsyncSession) -> None:
        user = await make_user(session)
        enrolment = await account.begin_totp_enrolment(session, user)
        await account.confirm_totp_enrolment(session, user, totp.code_at(enrolment.secret, _now()))

        with pytest.raises(ForbiddenError):
            await account.disable_totp(session, user, current_password="wrong")

        assert await account.is_totp_active(session, user) is True

    async def test_the_right_password_removes_it(self, session: AsyncSession) -> None:
        user = await make_user(session)
        enrolment = await account.begin_totp_enrolment(session, user)
        await account.confirm_totp_enrolment(session, user, totp.code_at(enrolment.secret, _now()))

        await account.disable_totp(session, user, current_password=PASSWORD)

        assert await account.is_totp_active(session, user) is False
        result = await webauth.login(session, username="ada", password=PASSWORD)
        assert result.needs_factor is None

    async def test_removing_one_that_is_not_there_is_refused(self, session: AsyncSession) -> None:
        user = await make_user(session)

        with pytest.raises(InvalidInputError):
            await account.disable_totp(session, user, current_password=PASSWORD)


class TestSessions:
    async def test_they_are_listed(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await websessions.create(session, user, user_agent="Firefox")
        await websessions.create(session, user, user_agent="a phone")

        listed = await account.list_sessions(session, user)

        assert len(listed) == 2
        assert {record.user_agent for record in listed} == {"Firefox", "a phone"}

    async def test_only_this_account_s_sessions_are_listed(self, session: AsyncSession) -> None:
        user = await make_user(session)
        other = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        await websessions.create(session, other)

        assert await account.list_sessions(session, user) == []

    async def test_one_can_be_ended(self, session: AsyncSession) -> None:
        user = await make_user(session)
        token, record = await websessions.create(session, user)
        _, here = await websessions.create(session, user)

        await account.revoke_session(session, user, record.id, current=here)

        assert await websessions.lookup(session, token) is None

    async def test_somebody_else_s_cannot_be_ended(self, session: AsyncSession) -> None:
        user = await make_user(session)
        other = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )
        token, theirs = await websessions.create(session, other)
        _, here = await websessions.create(session, user)

        with pytest.raises(ForbiddenError):
            await account.revoke_session(session, user, theirs.id, current=here)

        assert await websessions.lookup(session, token) is not None

    async def test_everywhere_else_can_be_signed_out_at_once(self, session: AsyncSession) -> None:
        user = await make_user(session)
        elsewhere, _ = await websessions.create(session, user)
        here_token, here = await websessions.create(session, user)

        await account.revoke_other_sessions(session, user, keep=here)

        assert await websessions.lookup(session, elsewhere) is None
        assert await websessions.lookup(session, here_token) is not None
