"""Deleting what nobody asked to keep.

zotero.org empties the trash after thirty days. A self-hosted server can make
that period the operator's own — including never, which is the default here,
because an upgrade that started deleting somebody's trash would be a surprise
of the worst kind. What the periods are and where they come from is
:mod:`altero.services.instancesettings`; this is what applies them.

The trash is the sharp one, and it is deliberately not a ``DELETE`` statement.
Removing rows quietly would leave every client that had synced holding items
this server no longer has, with no way to find out short of a full
re-download. So it goes through the same :func:`~altero.services.itemwrites.
delete_items` a client's own delete goes through: the library takes one new
version, the deletions are recorded, and the next ``/deleted?since=`` tells
every client exactly what went. One new version per library swept, however many
items go, which is the rule everywhere else in this server.

**Age is read from ``server_date_modified``.** There is no column saying when
an item was put in the trash, and adding one would leave every item already in
there with nothing in it. The server's own timestamp says the item changed no
later than that, so an item touched while in the trash gets a fresh lease and
is deleted late rather than early. Late is the right direction to be wrong in.

Safe to run twice at once, and safe to run alongside a request: each library is
locked while it is swept, and deleting an item that has already gone is not an
error.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import (
    ActivityKind,
    EmailVerification,
    GroupActivity,
    GroupActivityObject,
    Invitation,
    Item,
    Library,
    StorageUpload,
    WebSession,
)
from altero.services import groupactivity, itemwrites, storage, writes

logger = logging.getLogger("altero.retention")


@dataclass(frozen=True, slots=True)
class Report:
    """What a sweep did, or would have done."""

    #: Items deleted out of the trash for good.
    items_deleted: int = 0
    #: Libraries that had any, each of which took one new version.
    libraries: int = 0
    #: Delivered group activity rows removed.
    activity: int = 0
    #: Authorizations whose bytes never arrived.
    uploads: int = 0
    #: Browser sessions past their expiry.
    sessions: int = 0
    #: Confirmation links past theirs.
    verifications: int = 0
    #: Invitations that expired without ever being answered.
    invitations: int = 0

    @property
    def anything(self) -> bool:
        return bool(
            self.items_deleted
            or self.activity
            or self.uploads
            or self.sessions
            or self.verifications
            or self.invitations
        )


def _now() -> datetime:
    """The moment the sweep is about, in the form the columns hold."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _sweep_trash(
    session: AsyncSession, days: int, *, now: datetime, dry_run: bool
) -> tuple[int, int]:
    """Delete trashed items older than ``days``. Returns items and libraries."""
    if days <= 0:
        return 0, 0

    cutoff = now - timedelta(days=days)
    rows = await session.execute(
        select(Item.library_id, Item.key)
        .where(Item.deleted.is_(True), Item.server_date_modified < cutoff)
        .order_by(Item.library_id, Item.id)
    )

    by_library: dict[int, list[str]] = {}
    for library_id, key in rows:
        by_library.setdefault(library_id, []).append(key)

    if dry_run:
        return sum(len(keys) for keys in by_library.values()), len(by_library)

    deleted = 0
    for library_id, keys in by_library.items():
        library = await session.get(Library, library_id)
        if library is None:  # pragma: no cover - defensive
            continue

        library = await writes.lock_library(session, library)
        # Named before they go: there is nothing left to read afterwards.
        named = await groupactivity.name_items(session, library, keys)
        version = await writes.bump_library_version(session, library)
        await itemwrites.delete_items(session, library, keys, version)
        await groupactivity.record(
            session,
            library,
            # Nobody did this. A digest naming a member who had not touched
            # the library in months would be a lie about who deleted what.
            actor_id=None,
            kind=ActivityKind.ITEMS_DELETED,
            count=len(keys),
            objects=named,
        )
        await session.commit()
        deleted += len(keys)

    return deleted, len(by_library)


async def _sweep_activity(session: AsyncSession, days: int, *, now: datetime, dry_run: bool) -> int:
    """Remove delivered group activity older than ``days``.

    Only *delivered* rows. One still waiting is not old however long ago it
    happened: taking it would silently unsubscribe everybody whose digest was
    waiting on a relay that was down.
    """
    if days <= 0:
        return 0

    cutoff = now - timedelta(days=days)
    doomed = list(
        await session.scalars(
            select(GroupActivity.id).where(
                GroupActivity.flushed.is_not(None), GroupActivity.created < cutoff
            )
        )
    )
    if dry_run or not doomed:
        return len(doomed)

    # By hand rather than by cascade: a bulk delete does not load the rows, so
    # the ORM's delete-orphan on `objects` never runs and the names would be
    # left pointing at activity that had gone.
    await session.execute(
        delete(GroupActivityObject).where(GroupActivityObject.activity_id.in_(doomed))
    )
    await session.execute(delete(GroupActivity).where(GroupActivity.id.in_(doomed)))
    await session.commit()
    return len(doomed)


async def _sweep_uploads(session: AsyncSession, hours: int, *, now: datetime, dry_run: bool) -> int:
    """Forget authorizations whose bytes never arrived.

    Nothing is lost by forgetting one: the client asks permission again. The
    file protocol writes a row per authorization and only a completed upload
    clears it, so without this the table keeps every abandoned one.
    """
    if hours <= 0:
        return 0

    before = now - timedelta(hours=hours)
    if dry_run:
        return len(
            list(
                await session.scalars(
                    select(StorageUpload.key).where(
                        StorageUpload.received.is_(False), StorageUpload.created < before
                    )
                )
            )
        )

    purged = await storage.purge_stale_uploads(session, before)
    await session.commit()
    return purged


async def _sweep_expired(session: AsyncSession, *, now: datetime, dry_run: bool) -> Report:
    """Remove rows that are past their own expiry.

    No period of their own, because they carry one: a session that expired is
    already nobody's session, and a confirmation link past its hour confirms
    nothing. Only *unanswered* invitations go — one that was accepted or
    declined is kept on purpose, so that re-inviting somebody who said no is a
    visible act.
    """
    sessions = list(await session.scalars(select(WebSession.id).where(WebSession.expires < now)))
    verifications = list(
        await session.scalars(select(EmailVerification.id).where(EmailVerification.expires < now))
    )
    invitations = list(
        await session.scalars(
            select(Invitation.id).where(Invitation.status == "pending", Invitation.expires < now)
        )
    )

    if not dry_run:
        for model, doomed in (
            (WebSession, sessions),
            (EmailVerification, verifications),
            (Invitation, invitations),
        ):
            if doomed:
                await session.execute(delete(model).where(model.id.in_(doomed)))
        await session.commit()

    return Report(
        sessions=len(sessions),
        verifications=len(verifications),
        invitations=len(invitations),
    )


async def sweep(
    session: AsyncSession,
    values: dict[str, int],
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> Report:
    """Apply every retention period and report what it did.

    ``values`` is what :func:`altero.services.instancesettings.read_all`
    returns. Passed in rather than read here so that the command line can
    answer "what would 30 days do" without storing 30 days first.
    """
    moment = now or _now()

    items, libraries = await _sweep_trash(
        session, values.get("trashRetentionDays", 0), now=moment, dry_run=dry_run
    )
    activity = await _sweep_activity(
        session, values.get("activityRetentionDays", 0), now=moment, dry_run=dry_run
    )

    uploads = await _sweep_uploads(
        session, values.get("uploadRetentionHours", 0), now=moment, dry_run=dry_run
    )
    expired = await _sweep_expired(session, now=moment, dry_run=dry_run)

    return Report(
        items_deleted=items,
        libraries=libraries,
        activity=activity,
        uploads=uploads,
        sessions=expired.sessions,
        verifications=expired.verifications,
        invitations=expired.invitations,
    )


def describe(report: Report) -> str:
    """Return one line saying what a sweep did, for a log and for the shell."""
    parts = []
    if report.items_deleted:
        parts.append(
            f"{report.items_deleted} items out of the trash in {report.libraries} libraries"
        )
    if report.activity:
        parts.append(f"{report.activity} delivered activity records")
    if report.uploads:
        parts.append(f"{report.uploads} abandoned uploads")
    if report.sessions:
        parts.append(f"{report.sessions} expired sessions")
    if report.verifications:
        parts.append(f"{report.verifications} expired confirmation links")
    if report.invitations:
        parts.append(f"{report.invitations} expired invitations")
    return ", ".join(parts) if parts else "nothing to delete"
