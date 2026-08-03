"""Email addresses on accounts, and confirming them.

Verification gates notifications and nothing else. An unverified account signs
in, syncs and reads its library exactly as a verified one does; what it does
not get is security mail, because sending "your password was changed" to an
address nobody has proved they control is how that notice reaches an attacker
instead of an owner.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.services import admin, emailverify, webauth, websessions

PASSWORD = "correct horse battery staple"


class TestRegistration:
    async def test_an_address_is_required(self, session: AsyncSession) -> None:
        with pytest.raises(InvalidInputError, match=r"[Ee]mail"):
            await webauth.register(session, username="ada", password=PASSWORD, email="")

    async def test_something_that_is_not_an_address_is_refused(self, session: AsyncSession) -> None:
        for candidate in ["ada", "ada@", "@example.org", "ada example.org", "a@b@c.org"]:
            with pytest.raises(InvalidInputError, match=r"[Ee]mail"):
                await webauth.register(session, username="ada", password=PASSWORD, email=candidate)

    async def test_the_address_is_stored_folded_to_lower_case(self, session: AsyncSession) -> None:
        """So that two people cannot hold the same address in different case."""
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="Ada@Example.ORG"
        )

        assert user.email == "ada@example.org"

    async def test_a_new_account_starts_unverified(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )

        assert user.email_verified is None

    async def test_the_address_must_not_already_be_in_use(self, session: AsyncSession) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        with pytest.raises(InvalidInputError):
            await webauth.register(
                session,
                username="grace",
                password=PASSWORD,
                email="ADA@example.org",
                allow_registration=True,
            )


class TestConfirming:
    async def test_the_right_token_verifies_the_address(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, user.email or "")

        confirmed = await emailverify.confirm(session, token)

        assert confirmed.id == user.id
        assert user.email_verified is not None

    async def test_the_token_is_stored_hashed(self, session: AsyncSession) -> None:
        """A database dump must not confirm anybody's address."""
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, "ada@example.org")

        pending = await emailverify.outstanding_for(session, user)

        assert pending is not None
        assert token not in pending.token_hash

    async def test_a_token_works_once(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, "ada@example.org")
        await emailverify.confirm(session, token)

        with pytest.raises(ForbiddenError):
            await emailverify.confirm(session, token)

    async def test_an_unknown_token_is_refused(self, session: AsyncSession) -> None:
        with pytest.raises(ForbiddenError):
            await emailverify.confirm(session, "not a real token")

    async def test_an_expired_token_is_refused(self, session: AsyncSession) -> None:
        from datetime import UTC, datetime, timedelta

        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, "ada@example.org")
        pending = await emailverify.outstanding_for(session, user)
        assert pending is not None
        pending.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(ForbiddenError):
            await emailverify.confirm(session, token)

    async def test_issuing_again_replaces_the_previous_token(self, session: AsyncSession) -> None:
        """ "Resend" must not leave the earlier link working."""
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        first = await emailverify.issue(session, user, "ada@example.org")

        second = await emailverify.issue(session, user, "ada@example.org")

        assert first != second
        with pytest.raises(ForbiddenError):
            await emailverify.confirm(session, first)
        assert (await emailverify.confirm(session, second)).id == user.id

    async def test_confirming_applies_the_address_the_token_was_issued_for(
        self, session: AsyncSession
    ) -> None:
        """A change of address is only adopted once the new one is proved.

        Otherwise a typo -- or somebody else's address -- becomes the account's
        contact address the moment it is typed, and the notice about the change
        goes there.
        """
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, "ada@newplace.org")

        assert user.email == "ada@example.org"

        await emailverify.confirm(session, token)

        assert user.email == "ada@newplace.org"
        assert user.email_verified is not None


class TestSigningInWithEither:
    async def test_the_username_still_works(self, session: AsyncSession) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        assert (await webauth.login(session, username="ada", password=PASSWORD)).token

    async def test_the_address_works_too(self, session: AsyncSession) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        result = await webauth.login(session, username="ada@example.org", password=PASSWORD)

        assert result.token

    async def test_the_address_is_matched_without_regard_to_case(
        self, session: AsyncSession
    ) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        assert (await webauth.login(session, username="ADA@Example.org", password=PASSWORD)).token

    async def test_an_unverified_address_can_still_sign_in(self, session: AsyncSession) -> None:
        """Verification gates notifications, not access."""
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        assert user.email_verified is None

        assert (await webauth.login(session, username="ada@example.org", password=PASSWORD)).token

    async def test_an_unknown_address_is_refused_in_the_same_words(
        self, session: AsyncSession
    ) -> None:
        """Widening the lookup must not widen what a refusal reveals."""
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        with pytest.raises(ForbiddenError) as unknown:
            await webauth.login(session, username="nobody@example.org", password=PASSWORD)
        with pytest.raises(ForbiddenError) as wrong:
            await webauth.login(session, username="ada", password="not the password")

        assert unknown.value.message == wrong.value.message

    async def test_a_username_may_not_contain_an_at_sign(self, session: AsyncSession) -> None:
        """Otherwise one identifier names two accounts.

        Sign-in takes a single field and picks the column from the shape of
        what was typed. A username holding "@" could therefore be somebody
        else's address, and whichever row the query returned first would decide
        who signs in -- leaving the other unreachable by the identifier its
        owner expects. Barring it at creation is what keeps that from arising.
        """
        with pytest.raises(InvalidInputError, match=r"@"):
            await webauth.register(
                session, username="grace@example.org", password=PASSWORD, email="g@example.org"
            )

    async def test_the_command_line_cannot_create_one_either(self, session: AsyncSession) -> None:
        """`altero user add` reaches the same rule, or it becomes the way round it."""
        with pytest.raises(InvalidInputError, match=r"@"):
            await admin.create_user(session, username="grace@example.org")

    async def test_an_identifier_with_an_at_sign_is_looked_up_only_as_an_address(
        self, session: AsyncSession
    ) -> None:
        await webauth.register(session, username="ada", password=PASSWORD, email="ada@example.org")

        with pytest.raises(ForbiddenError):
            await webauth.login(session, username="ada@wrong.org", password=PASSWORD)


class TestNotifications:
    async def test_a_verified_address_is_told_the_password_changed(
        self, session: AsyncSession
    ) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, "ada@example.org")
        await emailverify.confirm(session, token)
        sent: list = []

        await webauth.set_password(session, user, "another long password", notify=_recorder(sent))

        assert len(sent) == 1
        assert sent[0].to == "ada@example.org"
        assert "password" in sent[0].subject.lower()

    async def test_an_unverified_address_is_not_written_to(self, session: AsyncSession) -> None:
        """Nobody has proved they hold it, so a security notice sent there may
        be going to whoever typed it."""
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        sent: list = []

        await webauth.set_password(session, user, "another long password", notify=_recorder(sent))

        assert sent == []

    async def test_an_account_with_no_address_at_all_is_fine(self, session: AsyncSession) -> None:
        """Accounts made by `altero user add` have none."""
        user = await admin.create_user(session, username="grace")
        sent: list = []

        await webauth.set_password(session, user, PASSWORD, notify=_recorder(sent))

        assert sent == []

    async def test_a_notification_that_cannot_be_sent_does_not_undo_the_change(
        self, session: AsyncSession
    ) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        token = await emailverify.issue(session, user, "ada@example.org")
        await emailverify.confirm(session, token)

        async def explode(_: object) -> bool:
            raise OSError("relay is down")

        await webauth.set_password(session, user, "another long password", notify=explode)

        from altero.services import passwords

        assert passwords.verify_password(user.password_hash, "another long password") is True
        assert await websessions.lookup(session, "anything") is None


def _recorder(into: list):  # type: ignore[no-untyped-def]
    async def notify(message: object) -> bool:
        into.append(message)
        return True

    return notify
