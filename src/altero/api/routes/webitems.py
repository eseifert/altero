"""Filing, trashing, deleting, copying and publishing items from the browser.

The fifth module that writes to a library, and the first that writes to items.
Almost everything it does is something a person can express by dragging rows of
the item list somewhere: onto a collection, onto the library, onto the trash,
onto another library, or onto My Publications.

This is not a field editor, and it is one field away from not being one at all.
``rights`` can be written here (:data:`EDITABLE_FIELDS`), and no other field
can, because publishing a work sets its licence and a licence has to be
revisable by whoever set it — the desktop client revises it in its Info pane,
where ``rights`` is an ordinary field, and its My Publications wizard refuses to
run a second time on the same item. An interface that can publish and cannot
correct the terms would be worse than the client it copies. Everything else
about an item is still the desktop's to edit; a general field editor is a
larger thing than a line of this module, and it needs answers this does not
have.

The rules are the ones the rest of ``/web`` follows: a cookie and never an API
key, a CSRF token on anything that changes something, who may write decided by
:func:`altero.services.auth.user_access`, and the same
:mod:`altero.services.itemwrites` the v3 endpoints go through, so an item filed
here is filed the way a syncing client would have filed it — one new library
version, and the item at that version for every client to pick up.

Six deliberate departures from the v3 endpoints, all of them because a person
clicking is not a client reconciling:

**A selection is one errand.** Filing, trashing, restoring, deleting and copying
name their items in a list rather than in the path, because the reader who
picked out twenty rows and dragged them onto a collection did one thing.
Twenty requests would be twenty library versions, twenty entries in a group's
activity, and — if the tenth were refused — a selection half moved with nothing
to say so. So the items are named together, resolved together before anything is
written, and take one new version between them. A list of one is the ordinary
case and needs no separate door.

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

**The one field edit states the version it replaces.** Every other write here
is an errand the server works out against what is stored -- add this
collection, take that one away, set a flag -- so a page an hour old cannot
express a wrong one. Text can: somebody typing over a licence that another
client changed while the page sat open is a lost write, and the browser knows
which version it was shown. A stale one is refused rather than applied. It is
also the one write here that is about a single item and says so in its path,
because a version belongs to an item and a selection has no shared one.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.responses import library_headers
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import (
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
)
from altero.models import ActivityKind, Item, Library, User
from altero.serializers import item as render_item
from altero.services import auth, groupactivity, itemwrites, publications, writes
from altero.services import collections as collections_service
from altero.services import items as items_service

router = APIRouter(prefix="/web", tags=["web"])


#: The fields the browser may write, and the whole of that list.
#:
#: ``rights`` is here because the licence of a published work has to be
#: changeable by whoever published it, and this is where the desktop client
#: changes it: `rights` is an ordinary field in its Info pane, edited like any
#: other, and its My Publications wizard refuses to run twice on the same item
#: (`collectionTree.jsx`: "Item ... already exists in My Publications"). A
#: browser that could publish under a licence and never revise it would be
#: worse than the client it copies.
#:
#: An allowlist rather than "any field the schema knows", because everything
#: else in a library is still the desktop's to edit and a general field editor
#: is a larger thing than one line of this module -- it needs an answer for
#: creators, dates, notes and item types, and it needs one for what a browser
#: does with an item another client changed while the page sat open.
EDITABLE_FIELDS = frozenset({"rights"})


class ItemErrands(BaseModel):
    """What filing, trashing or restoring a selection takes from the browser.

    ``items`` holds one key or two hundred; the route makes no distinction,
    because the reader made none. Each of the other properties is a separate
    errand and any of them may be absent, so ``model_fields_set`` is what the
    route reads: ``deleted: false`` restores something from the trash and an
    absent ``deleted`` asks for nothing at all.
    """

    items: list[str] = Field(min_length=1)
    deleted: bool | None = None
    add_collections: list[str] = Field(default_factory=list, alias="addCollections")
    remove_collections: list[str] = Field(default_factory=list, alias="removeCollections")


class ItemFields(BaseModel):
    """The one text write: field values, and the version they replace."""

    #: Field values to write, by their API names. Only :data:`EDITABLE_FIELDS`.
    fields: dict[str, str]
    #: The version the browser last read. Absent is refused rather than assumed.
    version: int | None = None


class CopyRequest(BaseModel):
    """Which items are being copied, and where they are going."""

    items: list[str] = Field(min_length=1)
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


async def _rendered_all(
    session: AsyncSession, items: list[Item], library: Library, base_url: str
) -> list[dict[str, Any]]:
    """The items in the envelope the interface already reads elsewhere.

    One set of queries for the whole selection rather than one per item: every
    one of these helpers takes a list already, because the item list is drawn
    fifty rows at a time by the same means.
    """
    for item in items:
        await session.refresh(item)
    tags = await items_service.tags_for(session, items)
    collections = await items_service.collection_keys_for(session, items)
    parents = await items_service.parent_keys_for(session, items)
    children = await items_service.count_children(session, items)
    authors = await items_service.authors_for(session, items)

    return [
        render_item(
            item,
            library,
            base_url,
            tags=tags.get(item.id, []),
            collections=collections.get(item.id, []),
            num_children=children.get(item.id, 0),
            parent_key=parents.get(item.parent_id) if item.parent_id else None,
            authors=authors,
        )
        for item in items
    ]


async def _rendered(
    session: AsyncSession, item: Item, library: Library, base_url: str
) -> dict[str, Any]:
    """The one item in that same envelope."""
    return (await _rendered_all(session, [item], library, base_url))[0]


@router.patch("/libraries/{library_id}/items")
async def update_items(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    _csrf: CsrfDep,
    body: Annotated[ItemErrands, Body()],
) -> Response:
    """File a selection, take it out of a collection, trash it, or restore it.

    One request and one new library version, whether it names one item or two
    hundred: dragging a selection onto a collection is one thing the reader did.
    More than one errand fits in it too -- moving between collections is a
    removal and an addition, and two requests would be two versions again for
    something asked for once.

    Every item is resolved before anything is written, so a key that names
    nothing is a 404 with the library untouched rather than half a selection
    filed and the rest refused.
    """
    library = await _library(session, user, library_id, write=True)

    refiling = bool(body.add_collections or body.remove_collections)
    trashing = "deleted" in body.model_fields_set
    if not refiling and not trashing:
        raise InvalidInputError("Nothing to change")

    library = await writes.lock_library(session, library)
    # Named once each: a selection can hold the same row twice only through a
    # request nobody's interface would send, and writing an item twice would
    # give it two timestamps for one errand.
    keys = list(dict.fromkeys(body.items))
    items = [await items_service.get_item(session, library, key) for key in keys]

    version = await writes.bump_library_version(session, library)

    if refiling:
        # Read here rather than taken from the request: the page may be minutes
        # old, and a collection added from the desktop since it was drawn must
        # not disappear because the browser did not know about it. Per item,
        # because "take it out of where it is" is a different answer for each.
        current = await items_service.collection_keys_for(session, items)
        for item in items:
            filed = current.get(item.id, [])
            keep = [key for key in filed if key not in body.remove_collections]
            keep += [key for key in body.add_collections if key not in keep]
            await itemwrites.refile_item(session, library, item, keep, version, actor_id=user.id)

    if trashing:
        # Through `save_item` so that trashing from the browser is the write a
        # client makes when it trashes: same validation, same timestamps.
        for item in items:
            await itemwrites.save_item(
                session,
                library,
                {"deleted": bool(body.deleted)},
                version,
                key=item.key,
                replace=False,
                actor_id=user.id,
            )

    rendered = await _rendered_all(session, items, library, base_url)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_CHANGED,
        count=len(items),
        objects=await groupactivity.name_items(session, library, keys),
    )
    await session.commit()

    return JSONResponse({"items": rendered}, headers=library_headers(version))


@router.patch("/libraries/{library_id}/items/{item_key}")
async def update_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    body: Annotated[ItemFields, Body()],
) -> Response:
    """Write one of the fields the browser may write, on one item.

    The one write here that names a single item in its path, and the one that
    states the version it replaces. Every other change is an add-and-remove
    errand the server works out for itself against what is stored, so a stale
    page cannot express a wrong one; text is different. Somebody typing over a
    licence that another client changed while the page sat open is a lost write,
    and the browser knows which version it was shown. A version belongs to an
    item, which is why this is not something a selection can ask for.
    """
    library = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    if not body.fields:
        raise InvalidInputError("Nothing to change")
    if refused := sorted(set(body.fields) - EDITABLE_FIELDS):
        raise InvalidInputError(f"'{refused[0]}' cannot be changed here")
    if body.version is None:
        raise PreconditionRequiredError("Say which version you are changing")
    if body.version != item.version:
        raise PreconditionFailedError("The item has changed since you read it")

    version = await writes.bump_library_version(session, library)

    # Through `save_item`, which is what decides whether the field belongs to
    # this item type at all: a note has no `rights`, and the refusal for that is
    # the one a syncing client would get, from the same place.
    await itemwrites.save_item(
        session,
        library,
        dict(body.fields),
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


@router.delete("/libraries/{library_id}/items", status_code=204)
async def delete_items(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    item_key: Annotated[str, Query(alias="itemKey")],
    _csrf: CsrfDep,
) -> Response:
    """Remove the items named by ``itemKey``, and their children with them.

    Comma-separated keys, which is the shape the v3 ``DELETE`` on a collection
    of items takes, and one new library version for the lot.

    Only out of the trash, and only if *every* one of them is there. There is no
    undo in the browser, and an item removed here is gone from every client that
    syncs afterwards; the trash is the step that makes that recoverable, so it is
    not one this endpoint will skip for any item in the selection.

    No cap on how many. The v3 endpoint has one because a syncing client can
    always send another batch; a reader who selected everything in the trash
    cannot, and emptying the trash already deletes as much in one request.
    """
    library = await _library(session, user, library_id, write=True)

    keys = list(dict.fromkeys(key for key in item_key.split(",") if key))
    if not keys:
        raise InvalidInputError("'itemKey' parameter not provided")

    library = await writes.lock_library(session, library)
    for key in keys:
        item = await items_service.get_item(session, library, key)
        if not item.deleted:
            raise InvalidInputError("Move the item to the trash before deleting it")

    # Named before they go: there is nothing left to read afterwards.
    named = await groupactivity.name_items(session, library, keys)
    version = await writes.bump_library_version(session, library)
    await itemwrites.delete_items(session, library, keys, version)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_DELETED,
        count=len(keys),
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


@router.post("/libraries/{library_id}/items/copy", status_code=201)
async def copy_items(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    _csrf: CsrfDep,
    body: Annotated[CopyRequest, Body()],
) -> Response:
    """Copy items, with their notes and attachments, into another library.

    Two libraries, two permissions: the one they come out of has to be readable
    and is not touched, the one they go into has to be writable and is the only
    one whose version moves. Answering with the copies is what tells the browser
    which library to look in for them.

    One new version there however many items went, and the copies are made in
    the order they were named, so a selection arrives as a selection rather than
    as a scattering of separately-versioned items.
    """
    source = await _library(session, user, library_id, write=False)

    keys = list(dict.fromkeys(body.items))
    items = [await items_service.get_item(session, source, key) for key in keys]

    if body.library == library_id:
        raise InvalidInputError("An item is already in its own library")
    target = await _library(session, user, body.library, write=True)

    target = await writes.lock_library(session, target)
    if body.collection:
        # Resolved before anything is written, so a collection key from another
        # library is a 404 rather than half a copy.
        await collections_service.get_collection(session, target, body.collection)

    version = await writes.bump_library_version(session, target)
    copies = [
        await itemwrites.copy_item(
            session,
            target,
            item,
            version,
            collection_key=body.collection,
            actor_id=user.id,
        )
        for item in items
    ]

    rendered = await _rendered_all(session, copies, target, base_url)
    await groupactivity.record(
        session,
        target,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_CHANGED,
        count=len(copies),
        objects=await groupactivity.name_items(session, target, [copy.key for copy in copies]),
    )
    await session.commit()

    return JSONResponse({"items": rendered}, status_code=201, headers=library_headers(version))


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
