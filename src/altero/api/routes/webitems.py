"""Filing, trashing, deleting, copying and publishing items from the browser.

The fifth module that writes to a library, and the first that writes to items.
Everything it does is something a person can express by dragging one row of the
item list somewhere: onto a collection, onto the library, onto the trash, onto
another library, or onto My Publications. Nothing here is a field editor —
typing into an item is a different kind of write and a different set of
questions. Publishing does write one field, and only one: the licence the
reader chose, into ``rights``, decided by
:mod:`altero.services.publications` from a licence identifier rather than from
text the browser sent. That is part of what publishing *means* in the desktop
client, not an item being edited through the back door.

The rules are the ones the rest of ``/web`` follows: a cookie and never an API
key, a CSRF token on anything that changes something, who may write decided by
:func:`altero.services.auth.user_access`, and the same
:mod:`altero.services.itemwrites` the v3 endpoints go through, so an item filed
here is filed the way a syncing client would have filed it — one new library
version, and the item at that version for every client to pick up.

Four deliberate departures from the v3 endpoints, all of them because a person
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

**Publishing takes the answers the desktop's wizard takes.** ``inPublications``
is one boolean, and a browser that set it from a checkbox would publish a book
and silently leave its files and notes unpublished — or publish files under no
stated licence at all. So the endpoint takes what the wizard asks: whether the
files go, whether the notes go, and under what licence, with the same rules in
:mod:`altero.services.publications`. Taking an item out again takes its
children with it, because half a published work is not a state anybody asked
for.
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
from altero.services import auth, groupactivity, itemwrites, publications, writes
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


class PublicationTerms(BaseModel):
    """The answers the desktop client's wizard collects, and nothing besides.

    ``license`` is an identifier out of :data:`altero.services.publications
    .LICENSES` rather than the licence's name: the ``rights`` field of a
    published item is a statement people act on, so what goes into it is the
    server's to write. Absent means no licence was chosen, which is what the
    wizard means when no files are being published -- there is then nothing to
    license and the field is left as the reader wrote it.
    """

    include_files: bool = Field(default=False, alias="includeFiles")
    include_notes: bool = Field(default=False, alias="includeNotes")
    license: str | None = None
    keep_rights: bool = Field(default=True, alias="keepRights")


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


@router.put("/libraries/{library_id}/publications/items/{item_key}")
async def publish_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    body: Annotated[PublicationTerms, Body()],
) -> Response:
    """Put an item into My Publications on the terms the reader chose.

    The item and whichever of its children were asked for, all at the one new
    library version -- publishing a work and its files is one decision and one
    change, and a client syncing afterwards sees it as one.

    No group activity is recorded: a group library has no My Publications, and
    this refuses one before it writes anything.
    """
    library = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    version = await writes.bump_library_version(session, library)
    await publications.add_to_publications(
        session,
        library,
        item,
        version,
        include_files=body.include_files,
        include_notes=body.include_notes,
        license_id=body.license,
        keep_rights=body.keep_rights,
        actor_id=user.id,
    )

    rendered = await _rendered(session, item, library, base_url)
    await session.commit()

    return JSONResponse(rendered, headers=library_headers(version))


@router.delete("/libraries/{library_id}/publications/items/{item_key}")
async def unpublish_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
) -> Response:
    """Take an item out of My Publications, and its children with it.

    A ``DELETE`` on the published view of the item rather than on the item:
    what goes is its place in the list, and the item itself stays in the
    library with everything it holds. That is why it answers with the item
    instead of 204 -- there is still something to show, and the browser reads
    the same envelope back that publishing gave it.
    """
    library = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    version = await writes.bump_library_version(session, library)
    await publications.remove_from_publications(session, library, item, version, actor_id=user.id)

    rendered = await _rendered(session, item, library, base_url)
    await session.commit()

    return JSONResponse(rendered, headers=library_headers(version))
