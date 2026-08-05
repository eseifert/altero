"""Turning settled activity into one notification and one message.

The sweep is what makes this a digest rather than a stream. A client syncing a
library uploads in batches, so a member who asked to hear about new items would
otherwise be told ten times about one sync. Activity is therefore left alone
until the library has been quiet for a while, and then everything waiting is
rendered together.

Two rules decide who hears about it: the member asked for that kind, and the
member is not the person who did it. Both are checked here rather than at the
point of writing, so a group's size costs nothing on the sync path.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ActivityKind, GroupActivity, Library, Notification
from altero.services import groupactivity, groupdigest, groupprefs
from altero.services.mail import Message
from tests.factories import make_group, make_user

#: Long enough that nothing is due unless a test says so.
QUIET = timedelta(minutes=15)


class Outbox:
    """A mailer that keeps what it was given."""

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, message: Message) -> bool:
        self.sent.append(message)
        return True


@pytest.fixture
def outbox() -> Outbox:
    return Outbox()


@pytest.fixture
async def group(session: AsyncSession) -> Library:
    """A group whose owner writes and whose member subscribes to everything."""
    await make_user(session, user_id=1, username="alice", display_name="Alice")
    await make_user(session, user_id=2, username="bob", display_name="Bob", email="bob@example.org")
    library = await make_group(session, group_id=100, owner_id=1, members={2: "member"})
    for kind in ActivityKind:
        await groupprefs.set_kind(session, library, user_id=2, kind=kind, wanted=True)
    await session.commit()
    return library


async def age(session: AsyncSession, minutes: int) -> None:
    """Backdate every waiting row, so the sweep considers it settled."""
    when = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
    await session.execute(update(GroupActivity).values(created=when))
    await session.commit()


async def notices(session: AsyncSession, user_id: int) -> list[Notification]:
    result = await session.scalars(
        select(Notification).where(Notification.user_id == user_id).order_by(Notification.id)
    )
    return list(result)


async def record(
    session: AsyncSession,
    library: Library,
    *,
    kind: ActivityKind = ActivityKind.ITEMS_CHANGED,
    count: int = 1,
    actor_id: int | None = 1,
) -> None:
    await groupactivity.record(session, library, actor_id=actor_id, kind=kind, count=count)
    await session.commit()


class TestWhatIsDue:
    async def test_activity_that_has_not_settled_is_left_alone(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        # Somebody is mid-sync. Sending now would mean sending again in a
        # minute, which is the thing the quiet period exists to prevent.
        await record(session, group)

        sent = await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert sent == 0
        assert outbox.sent == []
        assert await notices(session, 2) == []

    async def test_activity_that_has_settled_is_delivered(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await record(session, group)
        await age(session, minutes=30)

        sent = await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert sent == 1
        assert len(outbox.sent) == 1
        assert len(await notices(session, 2)) == 1

    async def test_a_fresh_write_holds_back_the_whole_burst(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        # The burst is judged by its newest row, not its oldest: a sync still
        # running is one event that has not finished happening.
        await record(session, group)
        await age(session, minutes=30)
        await record(session, group)

        assert await groupdigest.sweep(session, outbox.send, quiet_period=QUIET) == 0
        assert outbox.sent == []


class TestWhoHearsAboutIt:
    async def test_the_person_who_did_it_is_not_told(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await groupprefs.set_kind(
            session, group, user_id=1, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()
        await record(session, group, actor_id=1)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert await notices(session, 1) == []
        assert len(await notices(session, 2)) == 1

    async def test_a_member_who_asked_for_nothing_hears_nothing(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        for kind in ActivityKind:
            await groupprefs.set_kind(session, group, user_id=2, kind=kind, wanted=False)
        await session.commit()
        await record(session, group)
        await age(session, minutes=30)

        assert await groupdigest.sweep(session, outbox.send, quiet_period=QUIET) == 0
        assert await notices(session, 2) == []

    async def test_only_the_subscribed_kinds_are_reported(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await groupprefs.set_kind(
            session, group, user_id=2, kind=ActivityKind.ITEMS_DELETED, wanted=False
        )
        await session.commit()
        await record(session, group, kind=ActivityKind.ITEMS_CHANGED, count=2)
        await record(session, group, kind=ActivityKind.ITEMS_DELETED, count=5)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        body = outbox.sent[0].body
        assert "2" in body
        assert "5" not in body

    async def test_each_person_hears_about_the_others_and_not_themselves(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        # Alice adds two, Bob adds three, both subscribe. Alice should be told
        # about three and Bob about two -- excluding the actor is per row, not
        # a decision about the whole burst.
        await groupprefs.set_kind(
            session, group, user_id=1, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()
        await record(session, group, actor_id=1, count=2)
        await record(session, group, actor_id=2, count=3)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        (for_alice,) = await notices(session, 1)
        (for_bob,) = await notices(session, 2)
        assert "3" in for_alice.body
        assert "2" not in for_alice.body
        assert "2" in for_bob.body
        assert "3" not in for_bob.body

    async def test_a_write_by_nobody_is_reported_to_everyone(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await record(session, group, actor_id=None)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert len(await notices(session, 2)) == 1


class TestWhatItSays:
    async def test_one_burst_becomes_one_message(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        # Ten batches of a sync are one thing that happened.
        for _ in range(10):
            await record(session, group, count=50)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert len(outbox.sent) == 1
        assert "500" in outbox.sent[0].body

    async def test_the_group_is_named(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await record(session, group)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert group.name in outbox.sent[0].subject

    async def test_the_notification_repeats_what_was_sent(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        # Mail is not enough on its own: no relay may be configured, and an
        # address may be unconfirmed. The panel is the other channel.
        await record(session, group, count=3)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        (notice,) = await notices(session, 2)
        assert notice.kind == "group_activity"
        assert group.name in notice.subject
        assert "3" in notice.body

    async def test_a_member_without_an_address_still_gets_the_notification(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await make_user(session, user_id=3, username="carol")
        from tests.factories import add_group_member

        await add_group_member(session, library_id=group.id, user_id=3)
        await groupprefs.set_kind(
            session, group, user_id=3, kind=ActivityKind.ITEMS_CHANGED, wanted=True
        )
        await session.commit()
        await record(session, group)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert len(await notices(session, 3)) == 1
        assert [message.to for message in outbox.sent] == ["bob@example.org"]


class TestNotSendingTwice:
    async def test_delivered_activity_is_not_sent_again(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await record(session, group)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)
        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert len(outbox.sent) == 1
        assert len(await notices(session, 2)) == 1

    async def test_delivered_rows_are_kept_and_stamped(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        # Kept rather than deleted: what accumulates is the record of who
        # changed what and when, which an activity log would be built from.
        await record(session, group)
        await age(session, minutes=30)

        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        rows = list(await session.scalars(select(GroupActivity)))
        assert len(rows) == 1
        assert rows[0].flushed is not None

    async def test_activity_after_a_sweep_is_delivered_separately(
        self, session: AsyncSession, group: Library, outbox: Outbox
    ) -> None:
        await record(session, group)
        await age(session, minutes=30)
        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        await record(session, group)
        await age(session, minutes=30)
        await groupdigest.sweep(session, outbox.send, quiet_period=QUIET)

        assert len(outbox.sent) == 2


class TestFailures:
    async def test_a_relay_that_refuses_still_leaves_the_notification(
        self, session: AsyncSession, group: Library
    ) -> None:
        # Nothing in the mail path raises, and a dead relay must not mean the
        # activity is delivered again on the next sweep.
        async def refuse(message: Message) -> bool:
            return False

        await record(session, group)
        await age(session, minutes=30)

        await groupdigest.sweep(session, refuse, quiet_period=QUIET)

        assert len(await notices(session, 2)) == 1
        rows = list(await session.scalars(select(GroupActivity)))
        assert rows[0].flushed is not None

    async def test_a_mailer_that_raises_does_not_lose_the_sweep(
        self, session: AsyncSession, group: Library
    ) -> None:
        async def explode(message: Message) -> bool:
            raise RuntimeError("relay on fire")

        await record(session, group)
        await age(session, minutes=30)

        # The digest is about something that already happened, so a failure to
        # announce it must not take anything else down with it.
        await groupdigest.sweep(session, explode, quiet_period=QUIET)

        assert len(await notices(session, 2)) == 1
