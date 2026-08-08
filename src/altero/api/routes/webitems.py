"""Filing, trashing, deleting and copying items from the browser.

The fifth module that writes to a library, and the first that writes to items.
Everything it does is something a person can express by dragging one row of the
item list somewhere: onto a collection, onto the library, onto the trash, or
onto another library. Nothing here edits an item's fields — that is a different
kind of write and a different set of questions.

The rules are the ones the rest of ``/web`` follows: a cookie and never an API
key, a CSRF token on anything that changes something, who may write decided by
:func:`altero.services.auth.user_access`, and the same
:mod:`altero.services.itemwrites` the v3 endpoints go through, so an item filed
here is filed the way a syncing client would have filed it — one new library
version, and the item at that version for every client to pick up.

Three deliberate departures from the v3 endpoints, all of them because a person
clicking is not a client reconciling:

**Filing says what changed, not what the result is.** ``addCollections`` and
``removeCollections`` rather than the whole ``collections`` array. A browser
that sent the array would be sending what it *believed* the item was in, from a
page that may be minutes old, and a collection added from the desktop in the
meantime would vanish without anyone asking for that. The server reads the
memberships inside the same locked transaction it writes them in.

**Deleting for good happens only out of the trash.** The browser has no undo,
so the trash is the undo: dragging to the trash sets ``deleted``, and only an
item already there can be removed outright. The v3 ``DELETE`` will delete
anything at any time, because a client that asks has already asked its user.

**Copying between libraries is a copy.** The original stays. A move would be a
delete somebody did not ask for, on the far side of a drag that can be started
by accident.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.responses import library_headers
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import ActivityKind, Item, Library, User
from altero.serializers import item as render_item
from altero.services import auth, groupactivity, itemwrites, writes
from altero.services import collections as collections_service
from altero.services import items as items_service

router = APIRouter(prefix="/web", tags=["web"])


class ItemChanges(BaseModel):
    """What changing an item takes from the browser.

    Each property is a separate errand and any of them may be absent, so
    ``model_fields_set`` is what the route reads: ``deleted: false`` restores
    something from the trash and an absent ``deleted`` asks for nothing at all.
    """

    deleted: bool | None = None
    add_collections: list[str] = Field(default_factory=list, alias="addCollections")
    remove_collections: list[str] = Field(default_factory=list, alias="removeCollections")


class CopyTarget(BaseModel):
    """Where a copied item is going: a library, and optionally a collection."""

    library: int
    collection: str | None = None


async def _library(session: AsyncSession, user: User, library_id: int, *, write: bool) -> Library:
    """Return the library if this person may read it, or change it."""
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")

    access = await auth.user_access(session, library, user.id)
    if write and not access.write:
        raise ForbiddenError("You cannot change this library")
    if not write and not access.read:
        raise ForbiddenError("You cannot read this library")
    return library


async def _rendered(
    session: AsyncSession, item: Item, library: Library, base_url: str
) -> dict[str, Any]:
    """The item in the envelope the interface already reads elsewhere."""
    await session.refresh(item)
    tags = (await items_service.tags_for(session, [item])).get(item.id, [])
    collections = (await items_service.collection_keys_for(session, [item])).get(item.id, [])
    parents = await items_service.parent_keys_for(session, [item])
    children = await items_service.count_children(session, [item])
    authors = await items_service.authors_for(session, [item])

    return render_item(
        item,
        library,
        base_url,
        tags=tags,
        collections=collections,
        num_children=children.get(item.id, 0),
        parent_key=parents.get(item.parent_id) if item.parent_id else None,
        authors=authors,
    )


@router.patch("/libraries/{library_id}/items/{item_key}")
async def update_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    body: Annotated[ItemChanges, Body()],
) -> Response:
    """File an item, take it out of a collection, trash it, or restore it.

    All of it in one request when a drag asks for more than one -- moving
    between collections is a removal and an addition, and two requests would be
    two library versions for something the reader did once.
    """
    library = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    refiling = bool(body.add_collections or body.remove_collections)
    trashing = "deleted" in body.model_fields_set
    if not refiling and not trashing:
        raise InvalidInputError("Nothing to change")

    version = await writes.bump_library_version(session, library)

    if refiling:
        # Read here rather than taken from the request: the page may be minutes
        # old, and a collection added from the desktop since it was drawn must
        # not disappear because the browser did not know about it.
        current = (await items_service.collection_keys_for(session, [item])).get(item.id, [])
        keys = [key for key in current if key not in body.remove_collections]
        keys += [key for key in body.add_collections if key not in keys]
        await itemwrites.refile_item(session, library, item, keys, version, actor_id=user.id)

    if trashing:
        # Through `save_item` so that trashing from the browser is the write a
        # client makes when it trashes: same validation, same timestamps.
        await itemwrites.save_item(
            session,
            library,
            {"deleted": bool(body.deleted)},
            version,
            key=item.key,
            replace=False,
            actor_id=user.id,
        )

    rendered = await _rendered(session, item, library, base_url)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_CHANGED,
        count=1,
        objects=await groupactivity.name_items(session, library, [item.key]),
    )
    await session.commit()

    return JSONResponse(rendered, headers=library_headers(version))


@router.delete("/libraries/{library_id}/items/{item_key}", status_code=204)
async def delete_item(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
) -> Response:
    """Remove an item that is in the trash, and its children with it.

    Only out of the trash. There is no undo in the browser, and an item removed
    here is gone from every client that syncs afterwards; the trash is the step
    that makes that recoverable, so it is not one this endpoint will skip.
    """
    library = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)
    if not item.deleted:
        raise InvalidInputError("Move the item to the trash before deleting it")

    # Named before it goes: there is nothing left to read afterwards.
    named = await groupactivity.name_items(session, library, [item.key])
    version = await writes.bump_library_version(session, library)
    await itemwrites.delete_items(session, library, [item.key], version)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_DELETED,
        count=1,
        objects=named,
    )
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))


@router.delete("/libraries/{library_id}/trash")
async def empty_trash(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    _csrf: CsrfDep,
) -> Response:
    """Delete every item in the trash, and answer with how many there were.

    The one place the browser deletes more than one thing at a time, and it is
    also the one place where that is what the reader means: the trash is a list
    of things already thrown away, and emptying it is the errand. It is still
    one request and one new library version, however many items go.

    Trashed *collections* are left alone. The browser never trashes one --
    deleting a collection here removes it outright -- so the only ones in there
    were trashed from the desktop, and they are not shown by anything this
    endpoint's caller can see. Emptying a trash should not remove objects the
    person emptying it was never shown.
    """
    library = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    trashed = list(
        await session.scalars(
            select(Item.key).where(Item.library_id == library.id, Item.deleted.is_(True))
        )
    )
    if not trashed:
        # Nothing was written, so nothing is a new version: a library that told
        # every syncing client it had changed because somebody looked at an
        # empty trash would be lying to all of them.
        return JSONResponse({"deleted": 0}, headers=library_headers(library.version))

    named = await groupactivity.name_items(session, library, trashed)
    version = await writes.bump_library_version(session, library)
    # Children of a trashed parent are removed with it by `delete_items`, and
    # a child that was trashed on its own is in `trashed` in its own right;
    # deleting something already gone is not an error there.
    await itemwrites.delete_items(session, library, trashed, version)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_DELETED,
        count=len(trashed),
        objects=named,
    )
    await session.commit()

    return JSONResponse({"deleted": len(trashed)}, headers=library_headers(version))


@router.post("/libraries/{library_id}/items/{item_key}/copy", status_code=201)
async def copy_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    body: Annotated[CopyTarget, Body()],
) -> Response:
    """Copy an item, with its notes and attachments, into another library.

    Two libraries, two permissions: the one it comes out of has to be readable
    and is not touched, the one it goes into has to be writable and is the only
    one whose version moves. Answering with the copy is what tells the browser
    which library to look in for it.
    """
    source = await _library(session, user, library_id, write=False)
    item = await items_service.get_item(session, source, item_key)

    if body.library == library_id:
        raise InvalidInputError("An item is already in its own library")
    target = await _library(session, user, body.library, write=True)

    target = await writes.lock_library(session, target)
    if body.collection:
        # Resolved before anything is written, so a collection key from another
        # library is a 404 rather than half a copy.
        await collections_service.get_collection(session, target, body.collection)

    version = await writes.bump_library_version(session, target)
    copy = await itemwrites.copy_item(
        session,
        target,
        item,
        version,
        collection_key=body.collection,
        actor_id=user.id,
    )

    rendered = await _rendered(session, copy, target, base_url)
    await groupactivity.record(
        session,
        target,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_CHANGED,
        count=1,
        objects=await groupactivity.name_items(session, target, [copy.key]),
    )
    await session.commit()

    return JSONResponse(rendered, status_code=201, headers=library_headers(version))
