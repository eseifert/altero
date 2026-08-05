"""What a member has asked to hear about, per group and per kind.

Kept on the membership rather than on the account, because "tell me about this
library" is the thing people actually want: somebody in five groups cares about
one of them, and a single account-wide switch would make them choose between
silence and all five.

Everything is off until it is turned on. altero sends nothing that is not a
direct consequence of a request -- see `docs/email.md` -- and an upgrade that
started mailing every member of every group would be exactly that.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import ActivityKind, Library
from altero.services import groupprefs
from tests.factories import make_group, make_user


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_user(session, user_id=2, username="member")
    return await make_group(session, group_id=100, owner_id=1, members={2: "member"})


class TestDefaults:
    async def test_a_new_member_hears_about_nothing(
        self, session: AsyncSession, group: Library
    ) -> None:
        assert await groupprefs.subscribed_kinds(session, group, user_id=2) == frozenset()

    async def test_every_kind_is_off(self, session: AsyncSession, group: Library) -> None:
        wanted = await groupprefs.get(session, group, user_id=2)

        assert wanted == dict.fromkeys(ActivityKind, False)


class TestSetting:
    async def test_turning_one_on_leaves_the_others_alone(
        self, session: AsyncSession, group: Library
    ) -> None:
        await groupprefs.set_kind(
            session, group, user_id=2, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()

        assert await groupprefs.subscribed_kinds(session, group, user_id=2) == {
            ActivityKind.ITEMS_CHANGED
        }

    async def test_a_kind_can_be_turned_off_again(
        self, session: AsyncSession, group: Library
    ) -> None:
        for wanted in (True, False):
            await groupprefs.set_kind(
                session, group, user_id=2, kind=ActivityKind.ITEMS_CHANGED, wanted=wanted
            )
        await session.commit()

        assert await groupprefs.subscribed_kinds(session, group, user_id=2) == frozenset()

    async def test_several_kinds_are_held_at_once(
        self, session: AsyncSession, group: Library
    ) -> None:
        for kind in (ActivityKind.ITEMS_CHANGED, ActivityKind.MEMBERS_CHANGED):
            await groupprefs.set_kind(session, group, user_id=2, kind=kind, wanted=True)
        await session.commit()

        assert await groupprefs.subscribed_kinds(session, group, user_id=2) == {
            ActivityKind.ITEMS_CHANGED,
            ActivityKind.MEMBERS_CHANGED,
        }

    async def test_members_choose_independently(
        self, session: AsyncSession, group: Library
    ) -> None:
        await groupprefs.set_kind(
            session, group, user_id=1, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()

        assert await groupprefs.subscribed_kinds(session, group, user_id=1) == {
            ActivityKind.ITEMS_CHANGED
        }
        assert await groupprefs.subscribed_kinds(session, group, user_id=2) == frozenset()

    async def test_a_stranger_cannot_subscribe(self, session: AsyncSession, group: Library) -> None:
        # Subscribing is not a way to find out that a private group exists, nor
        # to keep hearing about one you were removed from.
        await make_user(session, user_id=3, username="stranger")

        with pytest.raises(NotFoundError):
            await groupprefs.set_kind(
                session, group, user_id=3, kind=ActivityKind.ITEMS_CHANGED, wanted=True
            )

    def test_a_kind_arrives_from_the_wire_as_its_name(self) -> None:
        assert groupprefs.kind_from_name("items_changed") is ActivityKind.ITEMS_CHANGED

    def test_an_unknown_kind_is_refused(self) -> None:
        # The browser sends these names, so one that is not a kind is a client
        # error rather than something to quietly ignore.
        with pytest.raises(InvalidInputError):
            groupprefs.kind_from_name("items_renamed")

    def test_every_kind_has_a_name_that_round_trips(self) -> None:
        for kind in ActivityKind:
            assert groupprefs.kind_from_name(str(kind)) is kind


class TestResolvingRecipients:
    """Who the sweep will mail, which is the only question the flush asks."""

    async def test_only_subscribers_are_returned(
        self, session: AsyncSession, group: Library
    ) -> None:
        await groupprefs.set_kind(
            session, group, user_id=2, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()

        recipients = await groupprefs.subscribers(session, group, ActivityKind.ITEMS_CHANGED)

        assert [user.id for user in recipients] == [2]

    async def test_a_kind_nobody_wants_has_no_recipients(
        self, session: AsyncSession, group: Library
    ) -> None:
        await groupprefs.set_kind(
            session, group, user_id=2, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()

        assert await groupprefs.subscribers(session, group, ActivityKind.ITEMS_DELETED) == []

    async def test_someone_removed_from_the_group_stops_being_a_recipient(
        self, session: AsyncSession, group: Library
    ) -> None:
        from sqlalchemy import delete

        from altero.models import GroupMember

        await groupprefs.set_kind(
            session, group, user_id=2, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()
        await session.execute(
            delete(GroupMember).where(GroupMember.library_id == group.id, GroupMember.user_id == 2)
        )
        await session.commit()

        assert await groupprefs.subscribers(session, group, ActivityKind.ITEMS_CHANGED) == []
