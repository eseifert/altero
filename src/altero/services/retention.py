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
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import (
    ActivityKind,
    AuthRequest,
    ConsumedAssertion,
    EmailVerification,
    GroupActivity,
    GroupActivityObject,
    Invitation,
    Item,
    Library,
    LoginCode,
    OAuthAuthorizationRequest,
    OAuthCode,
    OAuthToken,
    StorageDownload,
    StorageUpload,
    WebAuthnChallenge,
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
    #: Sign-in codes sent by mail and never used.
    codes: int = 0
    #: Federated sign-ins that left here and never came back.
    federated: int = 0
    #: SAML assertions remembered past the point they could be replayed.
    assertions: int = 0
    #: Passkey ceremonies that were started and never answered.
    ceremonies: int = 0
    #: Confirmation links past theirs.
    verifications: int = 0
    #: Invitations that expired without ever being answered.
    invitations: int = 0
    #: Download permissions handed out with a redirect and not spent.
    downloads: int = 0
    #: Spent authorization requests, codes and tokens from the authorization
    #: server. Nothing is load-bearing once it has expired, and a table that
    #: only grows is one somebody finds the hard way.
    authorizations: int = 0

    @property
    def anything(self) -> bool:
        return bool(
            self.items_deleted
            or self.activity
            or self.uploads
            or self.sessions
            or self.codes
            or self.federated
            or self.assertions
            or self.ceremonies
            or self.verifications
            or self.invitations
            or self.downloads
            or self.authorizations
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
    libraries = 0
    for library_id in by_library:
        library = await session.get(Library, library_id)
        if library is None:  # pragma: no cover - defensive
            continue

        library = await writes.lock_library(session, library)
        # Candidates were read before the lock. Another request may have
        # restored, changed or deleted one while the sweep was waiting.
        # Re-read the eligibility predicate under the same lock all writers
        # take, before permanently removing anything.
        keys = list(
            await session.scalars(
                select(Item.key).where(
                    Item.library_id == library.id,
                    Item.deleted.is_(True),
                    Item.server_date_modified < cutoff,
                )
            )
        )
        if not keys:
            await session.commit()
            continue
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
        libraries += 1

    return deleted, libraries


async def _remove(
    session: AsyncSession, model: type[Any], condition: ColumnElement[bool], *, dry_run: bool
) -> int:
    """Delete the rows of ``model`` matching ``condition``, or count them on a dry run.

    One statement either way. Collecting the ids first and naming them would
    bind one value per row, which past a few tens of thousands is more than a
    statement can carry.
    """
    if dry_run:
        return await session.scalar(select(func.count()).select_from(model).where(condition)) or 0
    result = await session.execute(delete(model).where(condition))
    return getattr(result, "rowcount", 0) or 0


async def _sweep_activity(session: AsyncSession, days: int, *, now: datetime, dry_run: bool) -> int:
    """Remove delivered group activity older than ``days``.

    Only *delivered* rows. One still waiting is not old however long ago it
    happened: taking it would silently unsubscribe everybody whose digest was
    waiting on a relay that was down.
    """
    if days <= 0:
        return 0

    cutoff = now - timedelta(days=days)
    settled = and_(GroupActivity.flushed.is_not(None), GroupActivity.created < cutoff)
    if not dry_run:
        # By hand rather than by cascade: a bulk delete does not load the rows,
        # so the ORM's delete-orphan on `objects` never runs and the names would
        # be left pointing at activity that had gone.
        await session.execute(
            delete(GroupActivityObject).where(
                GroupActivityObject.activity_id.in_(select(GroupActivity.id).where(settled))
            )
        )
    removed = await _remove(session, GroupActivity, settled, dry_run=dry_run)
    if not dry_run:
        await session.commit()
    return removed


async def _sweep_uploads(session: AsyncSession, hours: int, *, now: datetime, dry_run: bool) -> int:
    """Forget authorizations nobody finished.

    Nothing is lost by forgetting one: the client asks permission again. The
    file protocol writes a row per authorization and only a completed upload
    clears it, so without this the table keeps every abandoned one -- whether
    the bytes never arrived, or arrived and were never registered.
    """
    if hours <= 0:
        return 0

    before = now - timedelta(hours=hours)
    if dry_run:
        return await _remove(session, StorageUpload, StorageUpload.created < before, dry_run=True)

    purged = await storage.purge_stale_uploads(session, before)
    await session.commit()
    return purged


async def _sweep_expired(session: AsyncSession, *, now: datetime, dry_run: bool) -> Report:
    """Remove rows that are past their own expiry.

    No period of their own, because they carry one: a session that expired is
    already nobody's session, a confirmation link past its hour confirms
    nothing, and a download permission past its five minutes opens nothing.
    Only *unanswered* invitations go — one that was accepted or declined is
    kept on purpose, so that re-inviting somebody who said no is a visible act.
    """
    counts: dict[str, int] = {}
    for name, model, condition in (
        # Codes first: they cascade from the sessions below, and deleting the
        # sessions would take them without the count reflecting it.
        ("codes", LoginCode, LoginCode.expires < now),
        ("sessions", WebSession, WebSession.expires < now),
        ("verifications", EmailVerification, EmailVerification.expires < now),
        (
            "invitations",
            Invitation,
            and_(Invitation.status == "pending", Invitation.expires < now),
        ),
        ("federated", AuthRequest, AuthRequest.expires < now),
        ("ceremonies", WebAuthnChallenge, WebAuthnChallenge.expires < now),
        ("assertions", ConsumedAssertion, ConsumedAssertion.expires < now),
        ("downloads", StorageDownload, StorageDownload.expires < now),
    ):
        counts[name] = await _remove(session, model, condition, dry_run=dry_run)

    authorizations = 0
    for model in (OAuthAuthorizationRequest, OAuthCode, OAuthToken):
        authorizations += await _remove(session, model, model.expires < now, dry_run=dry_run)

    if not dry_run:
        await session.commit()

    return Report(**counts, authorizations=authorizations)


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
        codes=expired.codes,
        federated=expired.federated,
        assertions=expired.assertions,
        ceremonies=expired.ceremonies,
        verifications=expired.verifications,
        invitations=expired.invitations,
        downloads=expired.downloads,
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
    if report.downloads:
        parts.append(f"{report.downloads} expired download permissions")
    if report.authorizations:
        parts.append(f"{report.authorizations} spent authorizations")
    return ", ".join(parts) if parts else "nothing to delete"
