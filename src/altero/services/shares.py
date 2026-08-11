"""Sharing one collection by link.

"Share a collection, not an entire library?" has been on the Zotero forums
since 2008 and is the longest-running request in this space. It is **not
implemented as sync**, and cannot be: the client's unit of sync is a library,
and scoping below one means either lying to a client about what a library holds
-- which breaks ``since`` and the version arithmetic every client depends on --
or patching clients, which is a non-goal. Nothing here is reachable with an API
key, nothing here moves a library version, and no sync client ever learns that
a share exists.

What it is instead is the other half of the request, and the half people
usually mean: a **page**. A read-only view of one collection, at a link that can
be sent to somebody with no account here, served by
:mod:`altero.api.routes.webshares` out of the same services and the same
serialiser as the library view. :mod:`altero.api.routes.webprofile` is the
precedent for a ``/web`` route that answers without a cookie.

Three things the link decides, and they are the whole of it:

- **How much of the tree.** ``subcollections`` shares the branch rather than
  the one collection, which is what the sidebar shows when you click it.
- **Whether the files go.** A bibliography is not the same thing to hand out as
  the PDFs, so it is a separate answer -- the same separation the desktop
  client's publishing wizard makes.
- **How long.** ``expires`` is optional, and an expired share answers exactly
  as a revoked one does: there is no such link.

The token is the whole credential. That is why it is 32 random bytes, why it is
never derived from anything about the collection, and why revoking is a delete:
a flag would leave the row for somebody to un-flag.

The trash is never shown. A shared collection is somebody's reading list, and
what they threw away is not on it.
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import Collection, CollectionShare, Library, User

#: Bytes of randomness in a token, matching the invitation links'. 32 bytes is
#: 43 URL-safe characters and is not guessable at any rate a server can be
#: asked questions at.
TOKEN_BYTES = 32

#: Most links one collection may carry at once. A share is a deliberate act and
#: a collection with fifty of them is a mistake or an attack, not a use.
MAX_PER_COLLECTION = 50


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


async def create_share(
    session: AsyncSession,
    library: Library,
    collection: Collection,
    *,
    creator: User,
    subcollections: bool = True,
    files: bool = True,
    expires: datetime | None = None,
) -> tuple[CollectionShare, str]:
    """Make a link to ``collection`` and return it with its token.

    The token is returned here and nowhere else, exactly as an invitation's is:
    what is stored is enough to serve the link and not enough to reconstruct
    it for somebody who has lost it. Losing it means making another.

    The caller commits.
    """
    if expires is not None and expires <= _now():
        raise InvalidInputError("An expiry has to be in the future")

    held = await session.scalar(
        select(CollectionShare).where(CollectionShare.collection_id == collection.id).limit(1)
    )
    if held is not None and len(await list_shares(session, collection)) >= MAX_PER_COLLECTION:
        raise InvalidInputError(
            f"A collection cannot have more than {MAX_PER_COLLECTION} links at once"
        )

    token = secrets.token_urlsafe(TOKEN_BYTES)
    share = CollectionShare(
        token=token,
        library_id=library.id,
        collection_id=collection.id,
        created_by_user_id=creator.id,
        created=_now(),
        expires=expires,
        subcollections=subcollections,
        files=files,
    )
    session.add(share)
    await session.flush()
    return share, token


async def list_shares(session: AsyncSession, collection: Collection) -> list[CollectionShare]:
    """Return every link to ``collection``, newest first."""
    result = await session.scalars(
        select(CollectionShare)
        .where(CollectionShare.collection_id == collection.id)
        .order_by(CollectionShare.created.desc(), CollectionShare.id.desc())
    )
    return list(result)


async def list_library_shares(session: AsyncSession, library: Library) -> list[CollectionShare]:
    """Return every link into ``library``, newest first.

    What the settings panel lists: somebody who wants to know what they have
    given away should not have to click through every collection to find out.
    """
    result = await session.scalars(
        select(CollectionShare)
        .where(CollectionShare.library_id == library.id)
        .order_by(CollectionShare.created.desc(), CollectionShare.id.desc())
    )
    return list(result)


async def get_share(session: AsyncSession, share_id: int) -> CollectionShare:
    """Return one link by its id, for revoking it."""
    share = await session.get(CollectionShare, share_id)
    if share is None:
        raise NotFoundError("No such link")
    return share


async def revoke(session: AsyncSession, share: CollectionShare) -> None:
    """Delete the link. The caller commits."""
    await session.delete(share)


async def revoke_for_collections(session: AsyncSession, collection_ids: list[int]) -> None:
    """Delete every link to any of ``collection_ids``.

    Called when a collection is deleted. A link to something that no longer
    exists is not a link that should answer 404 later: it is one that must stop
    existing at the moment the thing it pointed at did.
    """
    if not collection_ids:
        return
    await session.execute(
        delete(CollectionShare).where(CollectionShare.collection_id.in_(collection_ids))
    )


async def resolve(session: AsyncSession, token: str) -> tuple[CollectionShare, Library, Collection]:
    """Return what ``token`` names, or refuse.

    One answer -- 404 -- for a token that never existed, one that was revoked,
    one that has expired, and one whose collection has been trashed. They are
    the same fact from the reader's side: there is no such page. Distinguishing
    them would turn the link into a way of asking which tokens are real.
    """
    if not token:
        raise NotFoundError("No such link")

    share = await session.scalar(select(CollectionShare).where(CollectionShare.token == token))
    if share is None:
        raise NotFoundError("No such link")
    if share.expires is not None and share.expires <= _now():
        raise NotFoundError("No such link")

    collection = await session.get(Collection, share.collection_id)
    library = await session.get(Library, share.library_id)
    if collection is None or library is None or collection.deleted:
        raise NotFoundError("No such link")

    return share, library, collection


async def note_use(session: AsyncSession, share: CollectionShare) -> None:
    """Record that the link was followed, at a day's resolution.

    A day rather than an instant, and written only when it moves: the list needs
    to say whether a link is still in use, and a column rewritten on every
    request would turn reading a page into a write on every image and every
    attachment it holds. No address and no count is kept -- who read a public
    link is not something this server collects.
    """
    today = _now().replace(hour=0, minute=0, second=0)
    if share.last_used is not None and share.last_used >= today:
        return
    share.last_used = today
    await session.flush()
