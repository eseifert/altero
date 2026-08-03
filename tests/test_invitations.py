"""Inviting somebody to a group library, and telling them about it.

An invitation is addressed to an email address, not to a user, because the
common case is inviting somebody who has no account on this server yet. When
the address does match an account the invitation also appears in that person's
notifications, which is the difference between an invitation they can act on
and one that depends on their mail working.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import GroupMember, Library, User
from altero.services import admin, invitations, notifications, webauth

PASSWORD = "correct horse battery staple"


async def setup_group(session: AsyncSession) -> tuple[User, Library]:
    owner = await webauth.register(
        session, username="ada", password=PASSWORD, email="ada@example.org"
    )
    library = await admin.create_group(session, name="Analytical Engine", owner_username="ada")
    return owner, library


async def make_member(session: AsyncSession, username: str = "grace") -> User:
    return await webauth.register(
        session,
        username=username,
        password=PASSWORD,
        email=f"{username}@example.org",
        allow_registration=True,
    )


class TestInviting:
    async def test_an_admin_can_invite_an_address(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)

        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="Grace@Example.org"
        )

        assert invitation.email == "grace@example.org"
        assert invitation.status == invitations.PENDING
        assert invitation.role == "member"

    async def test_an_address_that_is_not_one_is_refused(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)

        with pytest.raises(InvalidInputError):
            await invitations.invite(session, library=library, inviter=owner, email="nonsense")

    async def test_it_is_linked_to_the_account_holding_that_address(
        self, session: AsyncSession
    ) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)

        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        assert invitation.user_id == grace.id

    async def test_inviting_a_stranger_leaves_it_unlinked(self, session: AsyncSession) -> None:
        """They can still accept: the emailed token is the credential."""
        owner, library = await setup_group(session)

        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="nobody@example.org"
        )

        assert invitation.user_id is None
        assert invitation.token_hash

    async def test_a_notification_is_raised_for_an_account_that_exists(
        self, session: AsyncSession
    ) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)

        await invitations.invite(session, library=library, inviter=owner, email="grace@example.org")

        unread = await notifications.list_for(session, grace)
        assert len(unread) == 1
        assert unread[0].kind == "invitation"
        assert "Analytical Engine" in unread[0].subject

    async def test_a_non_member_cannot_invite(self, session: AsyncSession) -> None:
        _, library = await setup_group(session)
        outsider = await make_member(session, "mallory")

        with pytest.raises(ForbiddenError):
            await invitations.invite(
                session, library=library, inviter=outsider, email="x@example.org"
            )

    async def test_an_ordinary_member_cannot_invite(self, session: AsyncSession) -> None:
        """Membership is not the same as being able to hand it out."""
        _, library = await setup_group(session)
        grace = await make_member(session)
        await admin.add_group_member(session, library, username="grace", role="member")

        with pytest.raises(ForbiddenError):
            await invitations.invite(session, library=library, inviter=grace, email="x@example.org")

    async def test_inviting_an_existing_member_is_refused(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)
        await make_member(session)
        await admin.add_group_member(session, library, username="grace")

        with pytest.raises(InvalidInputError, match="already"):
            await invitations.invite(
                session, library=library, inviter=owner, email="grace@example.org"
            )

    async def test_inviting_twice_reuses_the_outstanding_invitation(
        self, session: AsyncSession
    ) -> None:
        """Otherwise every reminder is a second row and a second live token."""
        owner, library = await setup_group(session)
        await make_member(session)

        first = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )
        second = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        assert second.id == first.id
        assert len(await invitations.pending_for_library(session, library)) == 1

    async def test_a_personal_library_cannot_be_invited_into(self, session: AsyncSession) -> None:
        owner, _ = await setup_group(session)
        personal = await session.get(Library, 1)
        assert personal is not None

        with pytest.raises(InvalidInputError):
            await invitations.invite(
                session, library=personal, inviter=owner, email="x@example.org"
            )


class TestAccepting:
    async def test_accepting_makes_the_person_a_member(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        await invitations.accept(session, invitation, grace)

        member = await session.scalar(
            GroupMember.__table__.select().where(
                GroupMember.library_id == library.id, GroupMember.user_id == grace.id
            )
        )
        assert member is not None
        assert invitation.status == invitations.ACCEPTED

    async def test_the_role_offered_is_the_role_granted(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org", role="admin"
        )

        await invitations.accept(session, invitation, grace)

        members = await admin.list_group_members(session, library)
        assert [m.role for m in members if m.user_id == grace.id] == ["admin"]

    async def test_it_cannot_be_accepted_twice(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )
        await invitations.accept(session, invitation, grace)

        with pytest.raises(ForbiddenError):
            await invitations.accept(session, invitation, grace)

    async def test_somebody_else_cannot_accept_it(self, session: AsyncSession) -> None:
        """The invitation names an address; holding the row is not consent."""
        owner, library = await setup_group(session)
        await make_member(session)
        mallory = await make_member(session, "mallory")
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        with pytest.raises(ForbiddenError):
            await invitations.accept(session, invitation, mallory)

    async def test_an_expired_invitation_cannot_be_accepted(self, session: AsyncSession) -> None:
        from datetime import UTC, datetime, timedelta

        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )
        invitation.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(ForbiddenError):
            await invitations.accept(session, invitation, grace)

    async def test_accepting_marks_its_notification_read(self, session: AsyncSession) -> None:
        """Acting on it is answering it; leaving it bold would be noise."""
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        await invitations.accept(session, invitation, grace)

        assert await notifications.unread_count(session, grace) == 0


class TestDeclining:
    async def test_declining_records_the_answer_without_membership(
        self, session: AsyncSession
    ) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        await invitations.decline(session, invitation, grace)

        assert invitation.status == invitations.DECLINED
        assert await admin.list_group_members(session, library) == [
            m for m in await admin.list_group_members(session, library) if m.user_id == owner.id
        ]

    async def test_a_declined_invitation_cannot_then_be_accepted(
        self, session: AsyncSession
    ) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )
        await invitations.decline(session, invitation, grace)

        with pytest.raises(ForbiddenError):
            await invitations.accept(session, invitation, grace)

    async def test_an_admin_can_revoke_one_that_is_still_outstanding(
        self, session: AsyncSession
    ) -> None:
        owner, library = await setup_group(session)
        grace = await make_member(session)
        invitation = await invitations.invite(
            session, library=library, inviter=owner, email="grace@example.org"
        )

        await invitations.revoke(session, invitation, owner)

        assert invitation.status == invitations.REVOKED
        with pytest.raises(ForbiddenError):
            await invitations.accept(session, invitation, grace)


class TestByToken:
    async def test_the_emailed_token_finds_the_invitation(self, session: AsyncSession) -> None:
        owner, library = await setup_group(session)

        invitation, token = await invitations.invite_with_token(
            session, library=library, inviter=owner, email="nobody@example.org"
        )

        assert (await invitations.by_token(session, token)).id == invitation.id

    async def test_an_unknown_token_finds_nothing(self, session: AsyncSession) -> None:
        with pytest.raises(NotFoundError):
            await invitations.by_token(session, "not a real token")

    async def test_somebody_who_registers_with_that_address_can_accept(
        self, session: AsyncSession
    ) -> None:
        """The whole point of inviting an address rather than an account."""
        owner, library = await setup_group(session)
        _, token = await invitations.invite_with_token(
            session, library=library, inviter=owner, email="newcomer@example.org"
        )

        newcomer = await webauth.register(
            session,
            username="newcomer",
            password=PASSWORD,
            email="newcomer@example.org",
            allow_registration=True,
        )
        found = await invitations.by_token(session, token)
        await invitations.accept(session, found, newcomer)

        assert found.status == invitations.ACCEPTED


class TestNotifications:
    async def test_they_come_back_newest_first(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        await notifications.raise_for(session, user, kind="security", subject="One")
        await notifications.raise_for(session, user, kind="security", subject="Two")

        listed = await notifications.list_for(session, user)

        assert [n.subject for n in listed] == ["Two", "One"]

    async def test_marking_one_read_lowers_the_count(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        first = await notifications.raise_for(session, user, kind="security", subject="One")
        await notifications.raise_for(session, user, kind="security", subject="Two")

        await notifications.mark_read(session, first, user)

        assert await notifications.unread_count(session, user) == 1

    async def test_marking_all_read_clears_the_count(self, session: AsyncSession) -> None:
        user = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        await notifications.raise_for(session, user, kind="security", subject="One")
        await notifications.raise_for(session, user, kind="security", subject="Two")

        await notifications.mark_all_read(session, user)

        assert await notifications.unread_count(session, user) == 0

    async def test_one_person_cannot_read_another_s(self, session: AsyncSession) -> None:
        ada = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        mallory = await make_member(session, "mallory")
        hers = await notifications.raise_for(session, ada, kind="security", subject="Private")

        with pytest.raises(ForbiddenError):
            await notifications.mark_read(session, hers, mallory)

    async def test_only_one_person_s_notifications_are_listed(self, session: AsyncSession) -> None:
        ada = await webauth.register(
            session, username="ada", password=PASSWORD, email="ada@example.org"
        )
        mallory = await make_member(session, "mallory")
        await notifications.raise_for(session, ada, kind="security", subject="Hers")

        assert await notifications.list_for(session, mallory) == []
