"""Shared collections: making a link, and reading one.

Two halves with two credentials, in one module because they are one feature and
splitting them would put the rule about what a link may reach in one file and
the rule about who may make one in another.

**Making a link** is under a cookie and a CSRF token like everything else that
changes something in ``/web``, and it takes write access to the library. Read
access is not enough: giving a collection away is a decision about the library
rather than a use of it, and somebody who may only read a group's items is not
the person to decide who else may. It moves no library version -- a share is
not a change to any object in the library, and telling every syncing client
that something happened when nothing did would be a lie to all of them.

**Reading one** answers with no cookie at all, and is the second part of
``/web`` to do so after :mod:`altero.api.routes.webprofile`. That is not a hole
in the boundary the rest of the package holds. It authenticates nobody, it
identifies nobody, and what it can reach is fixed at the moment the link was
made: one collection, optionally the branch under it, never the trash, and the
attachment bytes only if whoever made the link said so. There is no parameter a
reader can send that widens any of that -- the library and the collection come
out of the token, never out of the request.

Everything served here goes through the same services and the same serialiser
as the library view, so an item on a shared page is the item a syncing client
receives. What differs is which items exist.

A token that never was, one that has been revoked, one that has expired and one
whose collection has been thrown away all answer **404**. They are the same
fact from the reader's side, and distinguishing them would turn the link into a
way of asking which tokens are real.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from altero import cite, serializers
from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.api.routes.weblibrary import render_items
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import Collection, CollectionShare, Item, Library, User
from altero.query import ITEM_SORT_FIELDS, Direction, ListQuery, QuickSearchMode, default_direction
from altero.services import auth, items, shares, storage
from altero.services import collections as collections_service

router = APIRouter(prefix="/web", tags=["web"])

#: Largest page a shared collection will hand out at once, matching the library
#: view's.
MAX_LIMIT = 100

#: How a shared list is read by default. The person who made the link chose an
#: order for nothing, and a reading list is conventionally newest first.
DEFAULT_SORT = "dateModified"


class NewShare(BaseModel):
    """What making a link takes. Every answer has a default that gives less."""

    #: Whether the collections nested inside this one come along.
    subcollections: bool = True
    #: Whether attachment bytes are served, or only the metadata.
    files: bool = True
    #: When the link stops working, as an ISO 8601 instant. Absent means never.
    expires: str | None = None


class ShareChanges(BaseModel):
    """What can be changed about a link without replacing it.

    Not the token: a link somebody has already sent out either means what it
    meant or is revoked. Widening one that is already in circulation is a thing
    to do deliberately, which is what these three are; changing which
    collection it points at is not offered at all.
    """

    subcollections: bool | None = None
    files: bool | None = None
    expires: str | None = Field(default=None)
    #: Sent as ``true`` to clear an expiry, since ``null`` cannot be told from
    #: "not mentioned" in a partial write.
    never_expires: bool = Field(default=False, alias="neverExpires")


def _instant(value: str | None) -> datetime | None:
    """Parse an expiry, refusing anything that is not one."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidInputError("That is not a date and time") from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _moment(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


async def _writable(
    session: AsyncSession, user: User, library_id: int
) -> tuple[Library, auth.Access]:
    """Return the library if this person may give part of it away.

    Write access, not read. Handing a collection to whoever holds a link is a
    decision about the library rather than a use of it, and a member who may
    only read a group's items is not the person to make it.
    """
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")

    access = await auth.user_access(session, library, user.id)
    if not access.write:
        raise ForbiddenError("You cannot share from this library")
    return library, access


def _rendered(share: CollectionShare, collection: Collection, base_url: str) -> dict[str, Any]:
    """Render one link, without its token.

    The token is shown once, by the request that made it. Afterwards there is
    nothing here that would let somebody reading the list reconstruct a link
    they were not given -- which matters because reading the list takes write
    access to the library and following a link takes nothing at all.
    """
    return {
        "id": share.id,
        "collection": collection.key,
        "collectionName": collection.name,
        "subcollections": share.subcollections,
        "files": share.files,
        "created": _moment(share.created),
        "expires": _moment(share.expires),
        "lastUsed": _moment(share.last_used),
        "createdBy": share.created_by_user_id,
    }


@router.get("/libraries/{library_id}/shares")
async def list_library_shares(
    session: SessionDep, user: CurrentUserDep, base_url: BaseUrlDep, library_id: int
) -> Response:
    """Return every link into this library.

    Listed for the library rather than per collection, because the question
    somebody actually has is "what have I given away", and answering it a
    collection at a time would mean clicking through the whole tree.
    """
    library, _ = await _writable(session, user, library_id)

    payload = []
    for share in await shares.list_library_shares(session, library):
        collection = await session.get(Collection, share.collection_id)
        if collection is None:  # pragma: no cover - deleted with its collection
            continue
        payload.append(_rendered(share, collection, base_url))

    return JSONResponse({"shares": payload})


@router.post("/libraries/{library_id}/collections/{collection_key}/shares", status_code=201)
async def create_share(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    collection_key: str,
    _csrf: CsrfDep,
    body: Annotated[NewShare, Body()],
) -> Response:
    """Make a link to one collection, and answer with it once.

    The one response that carries the token. It is not stored anywhere it could
    be read back, so a link that is lost is replaced rather than recovered --
    the same rule the invitation links follow, for the same reason.

    No library version moves. A share is not a change to any object in the
    library, and a version that moved would tell every syncing client to come
    and fetch a change that does not exist.
    """
    library, _ = await _writable(session, user, library_id)
    collection = await collections_service.get_collection(session, library, collection_key)
    if collection.deleted:
        raise InvalidInputError("That collection is in the trash")

    share, token = await shares.create_share(
        session,
        library,
        collection,
        creator=user,
        subcollections=body.subcollections,
        files=body.files,
        expires=_instant(body.expires),
    )
    await session.commit()

    rendered = _rendered(share, collection, base_url)
    # The whole point of the request, and the only time it is ever sent.
    rendered["url"] = f"{base_url}/app/shared/{token}"
    return JSONResponse(rendered, status_code=201)


@router.patch("/shares/{share_id}")
async def update_share(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    share_id: int,
    _csrf: CsrfDep,
    body: Annotated[ShareChanges, Body()],
) -> Response:
    """Change what a link shows, or when it stops working."""
    share = await shares.get_share(session, share_id)
    await _writable(session, user, share.library_id)

    collection = await session.get(Collection, share.collection_id)
    if collection is None:  # pragma: no cover - deleted with its collection
        raise NotFoundError("No such link")

    if body.subcollections is not None:
        share.subcollections = body.subcollections
    if body.files is not None:
        share.files = body.files
    if body.never_expires:
        share.expires = None
    elif body.expires is not None:
        expires = _instant(body.expires)
        if expires is not None and expires <= datetime.now(UTC).replace(tzinfo=None):
            raise InvalidInputError("An expiry has to be in the future")
        share.expires = expires

    await session.commit()
    return JSONResponse(_rendered(share, collection, base_url))


@router.delete("/shares/{share_id}", status_code=204)
async def revoke_share(
    session: SessionDep, user: CurrentUserDep, share_id: int, _csrf: CsrfDep
) -> Response:
    """Stop the link working. A delete rather than a flag, so there is nothing
    left to turn back on."""
    share = await shares.get_share(session, share_id)
    await _writable(session, user, share.library_id)

    await shares.revoke(session, share)
    await session.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------
# The reading side: no cookie, and nothing but what the token decided
# --------------------------------------------------------------------------


async def _shared(session: AsyncSession, token: str) -> tuple[CollectionShare, Library, Collection]:
    """Return what the token names, noting that the link was followed."""
    share, library, collection = await shares.resolve(session, token)
    await shares.note_use(session, share)
    await session.commit()
    return share, library, collection


def _scope(share: CollectionShare, *, top: bool) -> items.Scope:
    """Which item scope this link means.

    The branch or the one collection, decided by the link and by nothing the
    reader can send. A shared page has no sidebar to narrow with, so there is no
    parameter here that a reader could use to reach an item the link does not
    already cover.
    """
    if share.subcollections:
        return items.Scope.COLLECTION_TREE_TOP if top else items.Scope.COLLECTION_TREE
    return items.Scope.COLLECTION_TOP if top else items.Scope.COLLECTION


async def _in_share(
    session: AsyncSession,
    share: CollectionShare,
    library: Library,
    collection: Collection,
    item_key: str,
) -> Item:
    """Return one item, if this link reaches it.

    Asked as a listing of one rather than by walking the item's collections,
    because that is the same question the page's own list answers and one
    implementation of it cannot disagree with itself. A child item is reached
    through its parent, which is why the scope here is the non-top one.
    """
    query = ListQuery(limit=1, item_keys=(item_key,))
    page = await items.list_items(
        session, library, query, scope=_scope(share, top=False), key=collection.key
    )
    if page.objects:
        return page.objects[0]

    # A note or an attachment is not filed anywhere itself; it belongs to the
    # item it hangs off, and the link reaches it exactly when it reaches that.
    item = await items.get_item(session, library, item_key)
    if item.parent_id is not None and not item.deleted:
        parent = await session.get(Item, item.parent_id)
        if parent is not None:
            reachable = await items.list_items(
                session,
                library,
                ListQuery(limit=1, item_keys=(parent.key,)),
                scope=_scope(share, top=False),
                key=collection.key,
            )
            if reachable.objects:
                return item

    raise NotFoundError("Item does not exist")


@router.get("/shared/{token}")
async def read_share(session: SessionDep, token: str) -> Response:
    """Describe the shared collection, for the page's heading.

    Names the collection and the library it came from, and nothing about who
    made the link or who else may read it. A reader holding a link is not
    somebody this server owes a roster to.
    """
    share, library, collection = await _shared(session, token)

    query = ListQuery(limit=1, sort="title", direction=Direction.ASCENDING)
    page = await items.list_items(
        session, library, query, scope=_scope(share, top=True), key=collection.key
    )

    return JSONResponse(
        {
            "collection": collection.name,
            "library": library.name,
            "subcollections": share.subcollections,
            "files": share.files,
            "numItems": page.total,
            "expires": _moment(share.expires),
        }
    )


@router.get("/shared/{token}/collections")
async def list_shared_collections(
    session: SessionDep, base_url: BaseUrlDep, token: str
) -> Response:
    """Return the collections under the shared one, for its own little tree.

    Empty when the link does not carry subcollections, rather than absent: the
    page draws the same way either way, with nothing to draw.
    """
    share, library, collection = await _shared(session, token)
    if not share.subcollections:
        return JSONResponse({"collections": []})

    nested = [
        entry
        for entry in await collections_service.subtree(session, collection)
        if entry.id != collection.id and not entry.deleted
    ]
    counts = await collections_service.count_items(session, nested)
    parents = await collections_service.parent_keys_for(session, nested)
    subcollections = await collections_service.count_subcollections(session, nested)

    return JSONResponse(
        {
            "root": collection.key,
            "collections": [
                serializers.collection(
                    entry,
                    library,
                    base_url,
                    num_collections=subcollections.get(entry.id, 0),
                    num_items=counts.get(entry.id, 0),
                    parent_key=parents.get(entry.parent_id) if entry.parent_id else None,
                )
                for entry in sorted(nested, key=lambda entry: entry.name.lower())
            ],
        }
    )


@router.get("/shared/{token}/items")
async def list_shared_items(
    session: SessionDep,
    base_url: BaseUrlDep,
    token: str,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    start: Annotated[int, Query(ge=0)] = 0,
    q: str | None = None,
    sort: str = DEFAULT_SORT,
    direction: Direction | None = None,
    collection: str | None = None,
) -> Response:
    """Return one page of the shared collection's items.

    ``collection`` narrows to one of the collections *inside* the shared one --
    the page's own tree, and never a way out of it: a key naming a collection
    the link does not cover answers 404, because it is resolved against the
    subtree rather than against the library.
    """
    share, library, root = await _shared(session, token)

    if sort not in ITEM_SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Cannot sort by {sort}")

    key = root.key
    if collection:
        if not share.subcollections:
            raise NotFoundError("Collection not found")
        inside = {entry.key for entry in await collections_service.subtree(session, root)}
        if collection not in inside:
            raise NotFoundError("Collection not found")
        key = collection

    query = ListQuery(
        limit=limit,
        start=start,
        q=q,
        qmode=QuickSearchMode.EVERYTHING if q else QuickSearchMode.TITLE_CREATOR_YEAR,
        sort=sort,
        direction=direction or default_direction(sort),
    )
    page = await items.list_items(session, library, query, scope=_scope(share, top=True), key=key)

    return JSONResponse(
        {
            "total": page.total,
            "items": await render_items(session, page.objects, library, base_url),
        }
    )


@router.get("/shared/{token}/items/{item_key}")
async def read_shared_item(
    session: SessionDep, base_url: BaseUrlDep, token: str, item_key: str
) -> Response:
    """Return one item of the shared collection, for the reading pane."""
    share, library, collection = await _shared(session, token)
    item = await _in_share(session, share, library, collection, item_key)

    (rendered,) = await render_items(session, [item], library, base_url)
    return JSONResponse(rendered)


@router.get("/shared/{token}/items/{item_key}/children")
async def list_shared_children(
    session: SessionDep, base_url: BaseUrlDep, token: str, item_key: str
) -> Response:
    """Return the notes and attachments hanging off one shared item.

    Whether the *files* can be downloaded is a separate question the link
    already answered; the attachments are listed either way, because an item
    whose PDF is not on offer still has one and a page that hid it would be
    describing a different item than the library holds.
    """
    share, library, collection = await _shared(session, token)
    await _in_share(session, share, library, collection, item_key)

    query = ListQuery(limit=MAX_LIMIT, sort="title", direction=Direction.ASCENDING)
    page = await items.list_items(session, library, query, scope=items.Scope.CHILDREN, key=item_key)
    children = [child for child in page.objects if not child.deleted]

    return JSONResponse(
        {
            "total": len(children),
            "items": await render_items(session, children, library, base_url),
        }
    )


@router.get("/shared/{token}/items/{item_key}/file")
async def download_shared_file(
    request: Request, session: SessionDep, token: str, item_key: str, download: bool = False
) -> Response:
    """Return an attachment's bytes, if the link was made to carry them.

    The one thing on this page that is refused rather than merely absent, and
    it is refused with a 404 like everything else here: a reader who was given
    a metadata-only link has no page on which the file exists.
    """
    share, library, collection = await _shared(session, token)
    if not share.files:
        raise NotFoundError("Item does not exist")

    item = await _in_share(session, share, library, collection, item_key)
    path, fields = await storage.stored_file(item, Path(request.app.state.settings.storage_path))

    content_type = fields.get("contentType") or "application/octet-stream"
    if not download and (charset := fields.get("charset")):
        content_type = f"{content_type}; charset={charset}"

    return FileResponse(
        path,
        media_type=content_type,
        filename=(fields.get("filename") or item.key) if download else None,
    )


@router.get("/shared/{token}/items/{item_key}/citation")
async def cite_shared_item(
    session: SessionDep,
    token: str,
    item_key: str,
    style: str = cite.DEFAULT_STYLE,
    locale: str = cite.DEFAULT_LOCALE,
) -> Response:
    """Return one shared item as a bibliography entry and an in-text citation.

    A shared reading list is the place somebody is most likely to want to cite
    from, and the server already renders these for the library view and the
    profile pages -- from the same CSL implementation, so a citation does not
    depend on which page it was taken from.
    """
    share, library, collection = await _shared(session, token)
    item = await _in_share(session, share, library, collection, item_key)

    csl = cite.csl_item(item, library)
    return JSONResponse(
        {
            "bib": cite.bibliography([csl], style=style, locale=locale),
            "citation": cite.citation(csl, style=style, locale=locale),
        }
    )
