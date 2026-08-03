"""Registration, login and web sessions, at the service layer.

These are the flows a person actually performs, so they are tested before
anything the API layer wraps around them. Nothing here touches HTTP: the
service takes a username and a password and hands back a session, and the
routes are responsible only for turning that into a cookie.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import Library, LibraryType, User, WebSession
from altero.services import admin, passwords, totp, webauth, websessions

PASSWORD = "correct horse battery staple"


async def make_user(session: AsyncSession, username: str = "ada") -> User:
    user = await admin.create_user(session, username=username, display_name="Ada")
    await webauth.set_password(session, user, PASSWORD)
    return user


class TestRegistration:
    async def test_the_first_account_may_always_be_registered(self, session: AsyncSession) -> None:
        """An empty instance has to be reachable without shell access.

        Registration closes again the moment it succeeds, so this is a way in
        for the owner rather than a way in for everyone.
        """
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )

        assert user.username == "ada"
        assert await webauth.registration_open(session) is False

    async def test_registration_creates_the_personal_library(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )

        library = await session.scalar(
            select(Library).where(Library.type == LibraryType.USER, Library.owner_id == user.id)
        )
        assert library is not None

    async def test_the_password_is_stored_hashed_and_not_in_the_clear(
        self, session: AsyncSession
    ) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )

        assert user.password_hash is not None
        assert PASSWORD not in user.password_hash
        assert passwords.verify_password(user.password_hash, PASSWORD) is True

    async def test_a_second_account_is_refused_while_registration_is_closed(
        self, session: AsyncSession
    ) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        with pytest.raises(ForbiddenError):
            await webauth.register(
                session, username="grace", password=PASSWORD, email="grace@example.org"
            )

    async def test_a_second_account_is_allowed_when_registration_is_opened(
        self, session: AsyncSession
    ) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        grace = await webauth.register(
            session,
            username="grace",
            password=PASSWORD,
            email="grace@example.org",
            allow_registration=True,
        )

        assert grace.username == "grace"

    async def test_a_duplicate_username_is_refused(self, session: AsyncSession) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        with pytest.raises(InvalidInputError):
            await webauth.register(
                session,
                username="ada",
                password=PASSWORD,
                email="ada@example.org",
                allow_registration=True,
            )

    async def test_a_short_password_is_refused_before_a_user_is_created(
        self, session: AsyncSession
    ) -> None:
        with pytest.raises(InvalidInputError):
            await webauth.register(
                session, username="ada", password="short", email="ada@example.org"
            )

        assert await session.scalar(select(User).where(User.username == "ada")) is None

    async def test_a_blank_username_is_refused(self, session: AsyncSession) -> None:
        with pytest.raises(InvalidInputError):
            await webauth.register(
                session, username="  ", password=PASSWORD, email="blank@example.org"
            )


class TestLogin:
    async def test_the_right_password_produces_an_authenticated_session(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)

        result = await webauth.login(session, username="ada", password=PASSWORD)

        assert result.needs_factor is None
        assert result.token
        assert result.session.user_id == user.id

    async def test_the_wrong_password_is_refused(self, session: AsyncSession) -> None:
        await make_user(session)

        with pytest.raises(ForbiddenError):
            await webauth.login(session, username="ada", password="not the password")

    async def test_an_unknown_user_is_refused_in_the_same_words(
        self, session: AsyncSession
    ) -> None:
        """The message must not distinguish a wrong name from a wrong password.

        Anything else turns the login form into a directory of who has an
        account here.
        """
        await make_user(session)

        with pytest.raises(ForbiddenError) as unknown:
            await webauth.login(session, username="nobody", password=PASSWORD)
        with pytest.raises(ForbiddenError) as wrong:
            await webauth.login(session, username="ada", password="not the password")

        assert unknown.value.message == wrong.value.message

    async def test_a_user_with_no_password_cannot_log_in(self, session: AsyncSession) -> None:
        """Accounts made by `altero user add` have no password until one is set."""
        await admin.create_user(session, username="grace")

        with pytest.raises(ForbiddenError):
            await webauth.login(session, username="grace", password=PASSWORD)

    async def test_the_username_is_matched_without_regard_to_case(
        self, session: AsyncSession
    ) -> None:
        await make_user(session)

        result = await webauth.login(session, username="ADA", password=PASSWORD)

        assert result.token

    async def test_a_weaker_stored_hash_is_upgraded_on_a_successful_login(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)
        user.password_hash = passwords.hash_password(PASSWORD, memory_cost=1024, time_cost=1)
        await session.commit()

        await webauth.login(session, username="ada", password=PASSWORD)

        await session.refresh(user)
        assert user.password_hash is not None
        assert passwords.needs_rehash(user.password_hash) is False
        assert passwords.verify_password(user.password_hash, PASSWORD) is True


class TestSessions:
    async def test_the_token_is_stored_hashed_so_the_table_is_not_a_key_ring(
        self, session: AsyncSession
    ) -> None:
        """Read access to the database must not hand over live sessions."""
        user = await make_user(session)

        token, record = await websessions.create(session, user)

        assert record.token_hash != token
        stored = await session.scalar(select(WebSession))
        assert stored is not None
        assert token not in stored.token_hash

    async def test_a_session_is_found_by_its_token(self, session: AsyncSession) -> None:
        user = await make_user(session)
        token, _ = await websessions.create(session, user)

        found = await websessions.lookup(session, token)

        assert found is not None
        assert found.user_id == user.id

    async def test_an_unknown_token_finds_nothing(self, session: AsyncSession) -> None:
        await make_user(session)

        assert await websessions.lookup(session, "not a real token") is None
        assert await websessions.lookup(session, "") is None
        assert await websessions.lookup(session, None) is None

    async def test_an_expired_session_finds_nothing(self, session: AsyncSession) -> None:
        user = await make_user(session)
        token, record = await websessions.create(session, user)
        record.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

        assert await websessions.lookup(session, token) is None

    async def test_a_revoked_session_stops_working_immediately(self, session: AsyncSession) -> None:
        user = await make_user(session)
        token, record = await websessions.create(session, user)

        await websessions.revoke(session, record)

        assert await websessions.lookup(session, token) is None

    async def test_every_session_gets_a_different_token(self, session: AsyncSession) -> None:
        user = await make_user(session)

        tokens = {(await websessions.create(session, user))[0] for _ in range(20)}

        assert len(tokens) == 20

    async def test_changing_the_password_revokes_every_other_session(
        self, session: AsyncSession
    ) -> None:
        """A password is changed because it may be known; the sessions it opened
        have to go with it, or the change achieves nothing."""
        user = await make_user(session)
        stale, _ = await websessions.create(session, user)
        kept_token, kept = await websessions.create(session, user)

        await webauth.set_password(session, user, "a different long password", keep=kept)

        assert await websessions.lookup(session, stale) is None
        assert await websessions.lookup(session, kept_token) is not None


class TestSecondFactor:
    async def test_a_user_without_a_second_factor_is_logged_straight_in(
        self, session: AsyncSession
    ) -> None:
        await make_user(session)

        result = await webauth.login(session, username="ada", password=PASSWORD)

        assert result.needs_factor is None
        assert result.session.pending_factor is None

    async def test_a_user_with_totp_gets_a_session_that_is_not_yet_authenticated(
        self, session: AsyncSession
    ) -> None:
        user = await make_user(session)
        await webauth.enrol_totp(session, user, confirm_with=None)

        result = await webauth.login(session, username="ada", password=PASSWORD)

        assert result.needs_factor == "totp"
        assert result.session.pending_factor == "totp"

    async def test_a_pending_session_does_not_count_as_authenticated(
        self, session: AsyncSession
    ) -> None:
        """Holding the cookie must not be enough while a factor is outstanding."""
        user = await make_user(session)
        await webauth.enrol_totp(session, user, confirm_with=None)
        result = await webauth.login(session, username="ada", password=PASSWORD)

        found = await websessions.lookup(session, result.token)

        assert found is not None
        assert websessions.is_authenticated(found) is False

    async def test_the_right_code_completes_the_session(self, session: AsyncSession) -> None:
        user = await make_user(session)
        secret = await webauth.enrol_totp(session, user, confirm_with=None)
        result = await webauth.login(session, username="ada", password=PASSWORD)

        await webauth.complete_totp(session, result.session, totp.code_at(secret, _now()))

        assert websessions.is_authenticated(result.session) is True

    async def test_the_wrong_code_leaves_the_session_pending(self, session: AsyncSession) -> None:
        user = await make_user(session)
        await webauth.enrol_totp(session, user, confirm_with=None)
        result = await webauth.login(session, username="ada", password=PASSWORD)

        with pytest.raises(ForbiddenError):
            await webauth.complete_totp(session, result.session, "000000")

        assert websessions.is_authenticated(result.session) is False

    async def test_a_code_cannot_be_used_twice(self, session: AsyncSession) -> None:
        """A code stays valid for its whole step; without a replay guard whoever
        else saw it gets a login out of it."""
        user = await make_user(session)
        secret = await webauth.enrol_totp(session, user, confirm_with=None)
        code = totp.code_at(secret, _now())

        first = await webauth.login(session, username="ada", password=PASSWORD)
        await webauth.complete_totp(session, first.session, code)

        second = await webauth.login(session, username="ada", password=PASSWORD)
        with pytest.raises(ForbiddenError):
            await webauth.complete_totp(session, second.session, code)

    async def test_enrolment_can_require_the_code_before_it_takes_effect(
        self, session: AsyncSession
    ) -> None:
        """Turning on a factor the user cannot produce locks them out, so the
        enrolment is only kept once they have proved they can."""
        user = await make_user(session)

        with pytest.raises(ForbiddenError):
            await webauth.enrol_totp(session, user, confirm_with="000000")

        result = await webauth.login(session, username="ada", password=PASSWORD)
        assert result.needs_factor is None


def _now() -> int:
    return int(datetime.now(UTC).timestamp())
