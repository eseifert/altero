"""Making, changing and removing collections from the browser.

Narrow in what it touches rather than in who may reach it: one collection at a
time, by name and by parent, and never an item. Sorting a library into
collections is what a library is *for*, and having to open the desktop client
to make one was the last thing the browser could not do to a library it can
otherwise read whole.

The rules are the ones the rest of ``/web`` follows. A cookie and never an API
key; a CSRF token on anything that changes something; and the same
:mod:`altero.services.objectwrites` the v3 endpoints go through, so a
collection made here is a collection made there -- same key, same validation,
same one new library version per request. Who may write is
:func:`altero.services.auth.user_access`, which is the key-less form of the
rule that decides it for a sync client.

Deleting is the v3 ``DELETE`` and not the desktop's trash: the collection goes,
its subcollections move up to where it was, and **its items stay in the
library**. Zotero offers deleting the items along with it; that is a write to
items, which the browser does not do, and a person who wants it can select them
in the client. What is here cannot lose anything that is not a collection.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.responses import library_headers
from altero.api.routes.collections import render_collection
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import ActivityKind, Collection, Library, User
from altero.services import auth, groupactivity, objectwrites, writes
from altero.services import collections as collections_service

router = APIRouter(prefix="/web", tags=["web"])

#: Longest name a collection may be given. Zotero's own column is 255
#: characters; a name is a label in a sidebar, and one that long is already
#: past anything a tree can show.
MAX_NAME = 255


class NewCollection(BaseModel):
    """What making a collection takes.

    A subset of the v3 payload on purpose. ``key`` and ``version`` are a
    syncing client's business -- it has objects of its own to reconcile -- and
    ``relations`` names other objects by URI, which nothing in the interface
    produces. What is left is the two things a person supplies.
    """

    name: str
    parent_collection: str | None = Field(default=None, alias="parentCollection")


class CollectionChanges(BaseModel):
    """What changing a collection takes: either property, or both.

    Which of them were *sent* is the question, not what they hold, so the
    defaults are meaningless on their own -- ``parentCollection: null`` asks
    for the top level and an absent one asks for nothing at all. The route
    reads ``model_fields_set`` to tell those apart.
    """

    name: str | None = None
    parent_collection: str | None = Field(default=None, alias="parentCollection")


async def _writable_library(
    session: AsyncSession, user: User, library_id: int
) -> tuple[Library, auth.Access]:
    """Return the library if this person may change it, with what they may do.

    Read access is not enough and is not checked separately: writing implies
    it. A group that reserves editing for its administrators refuses a member
    here exactly as it refuses their API key, and a member restricted to their
    own items is refused by the access this hands back -- a collection is the
    library's shared structure and belongs to nobody in particular.
    """
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")

    access = await auth.user_access(session, library, user.id)
    if not access.write:
        raise ForbiddenError("You cannot change this library")
    return library, access


@router.post("/libraries/{library_id}/collections", status_code=201)
async def create_collection(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    _csrf: CsrfDep,
    body: Annotated[NewCollection, Body()],
) -> Response:
    """Make one collection, optionally inside another.

    Answers with the collection in the same envelope the sidebar already reads,
    so the interface can show it without asking for the tree again -- though it
    does ask, because a new subcollection changes its parent's count too.
    """
    library, access = await _writable_library(session, user, library_id)

    name = body.name.strip()
    if not name:
        raise InvalidInputError("A collection needs a name")
    if len(name) > MAX_NAME:
        raise InvalidInputError(f"A collection name cannot be longer than {MAX_NAME} characters")

    payload: dict[str, Any] = {"name": name}
    if body.parent_collection:
        # Not checked here: `save_collection` resolves a parent within this
        # library and refuses one that is not in it, which is the same lookup.
        # A request naming a collection in somebody else's library is a 404,
        # and the whole transaction goes with it.
        payload["parentCollection"] = body.parent_collection

    # Locked before the version is read, for the reason in `services/writes.py`:
    # two requests that each read the version and add one hand out the same
    # number twice, and the second write is the one nobody ever sees again.
    library = await writes.lock_library(session, library)
    version = await writes.bump_library_version(session, library)
    collection = await objectwrites.save_collection(
        session, library, payload, version, permit=access
    )
    assert collection is not None  # A new collection is never "unchanged".

    rendered = await render_collection(session, collection, library, base_url)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.COLLECTIONS_CHANGED,
        count=1,
        objects=[(collection.key, collection.name)],
    )
    await session.commit()

    return JSONResponse(rendered, status_code=201, headers=library_headers(version))


async def _would_loop(session: AsyncSession, collection: Collection, parent: Collection) -> bool:
    """Whether making ``parent`` the parent of ``collection`` closes a loop.

    Walked upwards from the proposed parent, which is the shorter walk and
    needs no recursion. ``save_collection`` refuses only the one-step case --
    a collection named as its own parent -- and a two-step loop is just as
    fatal: everything in that branch would still exist and nothing would reach
    it, because a tree is drawn from parents and neither end has one.
    """
    seen = parent
    while True:
        if seen.id == collection.id:
            return True
        if seen.parent_id is None:
            return False
        above = await session.get(Collection, seen.parent_id)
        if above is None:
            return False
        seen = above


@router.patch("/libraries/{library_id}/collections/{collection_key}")
async def update_collection(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    collection_key: str,
    _csrf: CsrfDep,
    body: Annotated[CollectionChanges, Body()],
) -> Response:
    """Rename one collection, move it, or both.

    A patch and not a replacement: a property that was not sent keeps what is
    stored. The dialog this answers shows a name and a parent together, and one
    that cleared whichever the reader did not touch would lose a branch of the
    tree to a rename.

    ``parentCollection: null`` is how it says "no parent", which is what moving
    a collection back to the top level is. The stored form of that is ``false``,
    which is what comes back -- the v3 shape, unchanged.
    """
    library, access = await _writable_library(session, user, library_id)

    payload: dict[str, Any] = {}
    if "name" in body.model_fields_set:
        name = (body.name or "").strip()
        if not name:
            raise InvalidInputError("A collection needs a name")
        if len(name) > MAX_NAME:
            raise InvalidInputError(
                f"A collection name cannot be longer than {MAX_NAME} characters"
            )
        payload["name"] = name

    library = await writes.lock_library(session, library)
    collection = await collections_service.get_collection(session, library, collection_key)

    if "parent_collection" in body.model_fields_set:
        if body.parent_collection:
            parent = await collections_service.get_collection(
                session, library, body.parent_collection
            )
            if await _would_loop(session, collection, parent):
                raise InvalidInputError("A collection cannot be moved inside itself")
            payload["parentCollection"] = parent.key
        else:
            payload["parentCollection"] = False

    if not payload:
        raise InvalidInputError("Nothing to change")

    # A request that describes what is already stored still takes a version.
    # The alternative is answering with a version the library never had, and a
    # person pressing Save twice is not a reason to invent one.
    version = await writes.bump_library_version(session, library)
    changed = await objectwrites.save_collection(
        session, library, payload, version, key=collection.key, replace=False, permit=access
    )
    assert changed is not None  # Only the multi-object path asks to detect that.

    rendered = await render_collection(session, changed, library, base_url)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.COLLECTIONS_CHANGED,
        count=1,
        objects=[(changed.key, changed.name)],
    )
    await session.commit()

    return JSONResponse(rendered, headers=library_headers(version))


@router.delete("/libraries/{library_id}/collections/{collection_key}", status_code=204)
async def delete_collection(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    collection_key: str,
    _csrf: CsrfDep,
) -> Response:
    """Remove one collection. Its subcollections move up; its items stay.

    No ``If-Unmodified-Since-Version``, which the v3 endpoint requires. A sync
    client has a copy of the library to reconcile and must say what it last
    saw; a person clicking a row means that row, whatever else has happened to
    the library since the page was drawn. What the lock still guarantees is
    that this is one version of its own.
    """
    library, access = await _writable_library(session, user, library_id)

    library = await writes.lock_library(session, library)
    await collections_service.get_collection(session, library, collection_key)
    version = await writes.bump_library_version(session, library)
    await objectwrites.delete_collections(
        session, library, [collection_key], version, permit=access
    )
    await session.commit()

    # Nothing is recorded for the group's digest, because the v3 delete records
    # nothing either and there is no "collections deleted" for it to record --
    # a member should not hear about this only when it was done from a browser.
    return Response(status_code=204, headers=library_headers(version))
