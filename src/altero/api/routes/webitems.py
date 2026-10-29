"""Filing, trashing, deleting, copying and publishing items from the browser.

The fifth module that writes to a library, and the first that writes to items.
Almost everything it does is something a person can express by dragging rows of
the item list somewhere: onto a collection, onto the library, onto the trash,
onto another library, or onto My Publications.

One item is also created here, from the type picker (:func:`create_item`), and
edited: its fields, creators, tags, relations and note, or its type, through
:func:`update_item`. Its parent, its collections, the trash and My
Publications are each an errand of their own and are refused there by name
(:data:`NOT_EDITED_HERE`). A file comes in here as well, as a new attachment
(:func:`upload_attachment`) or in place of one's own (:func:`replace_file`),
the request body being the file.

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

**An edit states the version it replaces.** Every other write here is an
errand the server works out against what is stored -- add this collection,
take that one away, set a flag -- so a page an hour old cannot express a wrong
one. Text can: somebody typing over a title that another client changed while
the page sat open is a lost write, and the browser knows which version it was
shown. A stale one is refused rather than applied. It is
also the one write here that is about a single item and says so in its path,
because a version belongs to an item and a selection has no shared one.
"""

import re
import time
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import SplitResult, urlsplit

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import BaseUrlDep, SessionDep, UploadLimitDep
from altero.api.responses import library_headers
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.db import chunked
from altero.errors import (
    ConfirmationRequiredError,
    ForbiddenError,
    InvalidInputError,
    MissingObjectError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    RequestTooLargeError,
)
from altero.itemschema import get_schema
from altero.itemschema.typechange import change_type
from altero.models import ActivityKind, Item, Library, User
from altero.serializers import item as render_item
from altero.serializers import timestamp
from altero.services import auth, groupactivity, itemwrites, publications, storage, writes
from altero.services import collections as collections_service
from altero.services import items as items_service

router = APIRouter(prefix="/web", tags=["web"])


#: Properties of an item that an edit may not name, in ``fields`` or beside it.
#:
#: The first four are the server's or the client's bookkeeping and nobody's to
#: type. The next four are each changed by an errand of their own -- the parent by
#: what a note or attachment is created under, collections by filing, the trash
#: by trashing and My Publications by the wizard -- and an edit that carried
#: them would be a second, less careful way of doing the same thing. Named in ``fields``
#: they would otherwise have reached :func:`~altero.services.itemwrites
#: .save_item` as the property itself, since a v3 payload keeps both in one
#: object. The last six describe an attachment's bytes, and the upload writes
#: them from the bytes themselves: typed here, a digest would name a file the
#: attachment does not hold. Its ``filename`` is the one a person may change
#: (:func:`_renamed`).
NOT_EDITED_HERE = frozenset(
    {
        "key",
        "version",
        "dateAdded",
        "dateModified",
        "parentItem",
        "collections",
        "deleted",
        "inPublications",
        "linkMode",
        "md5",
        "mtime",
        "contentType",
        "charset",
        "path",
    }
)

#: What an edit may carry besides ``fields``, each as the v3 API spells it.
#: Sent empty, a list clears what it names; left out, it is left alone.
EDITED_PROPERTIES = ("creators", "tags", "relations", "note")


#: Item types the browser does not make from a bare template.
#:
#: An attachment is made with the file or the link it holds, and a template
#: alone would be one with neither: a file comes in by the upload, and a web
#: link is the one attachment made here, with its address (:data:`WEB_LINK`).
#: An annotation belongs to a reader.
NOT_CREATED_HERE = frozenset({"attachment", "annotation"})

#: The one attachment made from a template here: the desktop's *Attach Web Link…*.
WEB_LINK = "linked_url"

#: Schemes `Zotero.Attachments.linkFromURL` refuses, and ``file``, which its
#: dialog sends to *Attach Link to File…* instead -- a path on somebody's own
#: computer, which nothing on this server can open.
UNLINKABLE_SCHEMES = frozenset({"javascript", "data", "chrome", "resource", "mailto", "file"})

_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]+):", re.IGNORECASE)


class NewItem(BaseModel):
    """What the type picker sends: the type, and where the new item goes.

    Nothing about its content. The item starts as the template `/items/new`
    serves and is filled in by edits, so there is one way of writing a field
    rather than two that could disagree about it.
    """

    item_type: str = Field(alias="itemType")
    #: The item a note or a web link is made under.
    parent_item: str | None = Field(default=None, alias="parentItem")
    #: The collection being looked at when it was made, usually.
    collections: list[str] = Field(default_factory=list)
    #: For an attachment, which can only be :data:`WEB_LINK`.
    link_mode: str | None = Field(default=None, alias="linkMode")
    #: A web link's address and title: an attachment with neither would be a
    #: link to nothing, so the content comes with it here.
    url: str | None = None
    title: str | None = None


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


class ItemEdit(BaseModel):
    """One item's changes, and the version they replace.

    The parts are the v3 item's own, so what reaches ``save_item`` is the patch
    a syncing client would have sent. Which of them were sent is
    ``model_fields_set``, because ``creators: []`` clears an item's creators and
    no ``creators`` at all leaves them be. Anything else is kept rather than
    dropped, so that the route can refuse it by name.
    """

    model_config = ConfigDict(extra="allow")

    #: Field values, by their API names.
    fields: dict[str, str] = Field(default_factory=dict)
    creators: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)
    relations: dict[str, Any] = Field(default_factory=dict)
    #: A note's HTML, or an attachment's note. Nothing else carries one.
    note: str = ""
    #: A new item type, sent on its own: see :func:`_retyped`.
    item_type: str | None = Field(default=None, alias="itemType")
    #: The fields the person agreed to lose by changing the type.
    discard: list[str] = Field(default_factory=list)
    #: The version the browser last read. Absent is refused rather than assumed.
    version: int | None = None

    def patch(self) -> dict[str, Any]:
        """The v3 partial item this edit amounts to.

        Raises:
            InvalidInputError: if it names a property it may not, or nothing.
        """
        extra = self.model_extra or {}
        for name in [*self.fields, *extra]:
            if name in NOT_EDITED_HERE:
                raise InvalidInputError(f"'{name}' cannot be changed here")
            if name in extra:
                raise InvalidInputError(f"Unknown property '{name}'")
            if name in itemwrites.STRUCTURAL_KEYS:
                # `creators` or `note` as a string field: their own property
                # says the same thing in the shape it has to have.
                raise InvalidInputError(f"Send '{name}' beside 'fields', not in it")

        patch: dict[str, Any] = dict(self.fields)
        for name in EDITED_PROPERTIES:
            if name in self.model_fields_set:
                patch[name] = getattr(self, name)
        if self.item_type is not None:
            if patch:
                raise InvalidInputError("Change the item type on its own")
            return {}
        if "discard" in self.model_fields_set:
            raise InvalidInputError("'discard' goes with a change of item type")
        if not patch:
            raise InvalidInputError("Nothing to change")
        return patch


def _renamed(item: Item, patch: dict[str, Any]) -> dict[str, Any]:
    """``patch`` with its new file name made the one the desktop would store.

    The desktop's attachment box renames the file and relinks the attachment to
    it (`renameAttachmentFile`, `relinkAttachmentFile`): the name goes through
    `getValidFileName`, the title stays, and the save skips `dateModified`,
    which a rename on its own here restates for the same effect. Nothing is
    uploaded again -- another desktop renames its own copy when it syncs the
    new `filename` -- so only a file stored on this server has a name to
    change; a link, and a linked file on somebody's disk, have none.
    """
    if (
        item.item_type != "attachment"
        or item.field_values().get("linkMode") not in REPLACEABLE_LINK_MODES
    ):
        raise InvalidInputError("Only a file stored here can be renamed")
    name = str(patch["filename"]).strip()
    if not name:
        raise InvalidInputError("A file needs a name")
    patch = {**patch, "filename": storage.valid_file_name(name)}
    if set(patch) == {"filename"}:
        patch["dateModified"] = timestamp(item.date_modified)
    return patch


def _retyped(item: Item, item_type: str, discard: list[str]) -> dict[str, Any]:
    """The v3 patch that changes ``item`` to ``item_type`` the way the desktop does.

    The desktop's own mapping rather than upstream's plainer one, so a book's
    author becomes a film's director as it would in the application beside
    this page; the patch names every field and creator, and the server's
    mapping finds nothing left to do. Fields with no place in the new type are
    lost, and the item pane asks first: so does this, by refusing until
    ``discard`` names exactly what the change throws away. A page showing an
    older warning names other fields and is asked again.

    Raises:
        ConfirmationRequiredError: listing the fields, until they are agreed to.
        InvalidInputError: for a note, an attachment or an annotation.
    """
    values = item.field_values()
    creators = [
        {"creatorType": creator.creator_type, "name": creator.name}
        if creator.name is not None
        else {
            "creatorType": creator.creator_type,
            "firstName": creator.first_name or "",
            "lastName": creator.last_name or "",
        }
        for creator in sorted(item.creators, key=lambda c: c.position)
    ]
    change = change_type(get_schema(), item.item_type, item_type, values, creators)
    if change.lost and sorted(discard) != sorted(change.lost):
        raise ConfirmationRequiredError(
            f"Changing the type loses {', '.join(change.lost)}", fields=change.lost
        )

    patch: dict[str, Any] = {"itemType": item_type, **change.fields}
    for name, value in values.items():
        if value and name not in change.fields:
            patch[name] = ""
    if creators:
        patch["creators"] = change.creators
    return patch


class RelatedItems(BaseModel):
    """The items to relate to the one in the path."""

    items: list[str] = Field(min_length=1)


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


async def _library(
    session: AsyncSession, user: User, library_id: int, *, write: bool
) -> tuple[Library, auth.Access]:
    """Return the library if this person may read it, or change it.

    The access comes back with it rather than being asked for again, because a
    group member restricted to adding, or to their own items, passes the check
    for the library and is refused per item further in -- and the object that
    answers that is this one.
    """
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")

    access = await auth.user_access(session, library, user.id)
    if write and not access.write:
        raise ForbiddenError("You cannot change this library")
    if not write and not access.read:
        raise ForbiddenError("You cannot read this library")
    return library, access


async def _rendered_all(
    session: AsyncSession, items: list[Item], library: Library, base_url: str
) -> list[dict[str, Any]]:
    """The items in the envelope the interface already reads elsewhere.

    One set of queries for the whole selection rather than one per item: every
    one of these helpers takes a list already, because the item list is drawn
    fifty rows at a time by the same means.
    """
    # Read again as stored, in one statement per chunk rather than a refresh
    # per item.
    for chunk in chunked([item.id for item in items]):
        await session.scalars(
            select(Item).where(Item.id.in_(chunk)).execution_options(populate_existing=True)
        )
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
    library, access = await _library(session, user, library_id, write=True)

    refiling = bool(body.add_collections or body.remove_collections)
    trashing = "deleted" in body.model_fields_set
    if not refiling and not trashing:
        raise InvalidInputError("Nothing to change")

    library = await writes.lock_library(session, library)
    # Named once each: a selection can hold the same row twice only through a
    # request nobody's interface would send, and writing an item twice would
    # give it two timestamps for one errand.
    keys = list(dict.fromkeys(body.items))
    items = await items_service.get_items(session, library, keys)

    version = await writes.bump_library_version(session, library)

    if refiling:
        await itemwrites.refile_items(
            session,
            library,
            items,
            version,
            add=body.add_collections,
            remove=body.remove_collections,
            actor_id=user.id,
            permit=access,
        )

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
                permit=access,
                stored=item,
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


@router.post("/libraries/{library_id}/items", status_code=201)
async def create_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    _csrf: CsrfDep,
    body: Annotated[NewItem, Body()],
) -> Response:
    """Make one empty item of a type, filed where it was asked for.

    The item is the v3 template for its type, written by the same `save_item`
    a client's upload goes through -- so its empty fields, its key and its
    version are what a client creating from `/items/new` would have produced,
    and the template's one nameless creator is dropped there, as upstream drops
    it. One request, one new version, and no precondition: nothing exists yet
    for a page to be stale about.

    A web link is the exception to "empty": its address and title come with
    it, as they come with the desktop's *Attach Web Link…*. It holds no file,
    so the group's ``fileEditing`` policy does not reach it, as the desktop
    offers it where files are not allowed.
    """
    library, access = await _library(session, user, library_id, write=True)
    linking = body.item_type == "attachment" and body.link_mode == WEB_LINK
    if body.item_type in NOT_CREATED_HERE and not linking:
        raise InvalidInputError(f"'{body.item_type}' items cannot be created here")

    if linking:
        payload = _web_link(body.url or "", body.title)
    else:
        payload = get_schema().template(body.item_type)
    if body.collections:
        payload["collections"] = list(dict.fromkeys(body.collections))

    library = await writes.lock_library(session, library)
    if body.parent_item is not None:
        if not linking and body.item_type != "note":
            raise InvalidInputError("Only a note or a link can be made under another item")
        payload["parentItem"] = await _parent_key(
            session, library, body.parent_item, access, child="a link" if linking else "a note"
        )

    version = await writes.bump_library_version(session, library)
    try:
        item = await itemwrites.save_item(
            session, library, payload, version, actor_id=user.id, permit=access
        )
    except MissingObjectError as missing:
        # The sync protocol's 409, which names the collection for a client to
        # upload. Here it is a collection gone since the page loaded, and the
        # browser's word for that is the 404 filing gives.
        raise NotFoundError(missing.message) from None
    assert item is not None
    await session.flush()

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

    return JSONResponse(rendered, status_code=201, headers=library_headers(version))


def _web_link(url: str, title: str | None) -> dict[str, Any]:
    """A ``linked_url`` attachment to ``url``, as `Zotero.Attachments.linkFromURL` makes one.

    Refused for an address with no scheme and for the schemes the desktop
    refuses, since the link is drawn as one and pressed. Without a title it is
    named after the address the desktop's way: a web address after the last
    part of its path, or its host when the path is ``/``; anything else after
    the whole address. And a link ending in ``.pdf`` is a PDF whatever the
    server would say, as the desktop decides it.
    """
    url = url.strip()
    scheme = _SCHEME.match(url)
    if scheme is None:
        raise InvalidInputError(f"'{url}' is not an address")
    if scheme.group(1).lower() in UNLINKABLE_SCHEMES:
        raise InvalidInputError(f"A link to a '{scheme.group(1)}' address cannot be attached")

    parts = urlsplit(url)
    payload = get_schema().template("attachment", WEB_LINK)
    payload["url"] = url
    payload["title"] = (title or "").strip() or _title_of(parts) or url
    if PurePosixPath(parts.path).suffix.lower() == ".pdf":
        payload["contentType"] = "application/pdf"
    return payload


def _title_of(parts: SplitResult) -> str:
    """The desktop's title for a web address: its file name, else its last directory."""
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    if parts.path in ("", "/"):
        return parts.hostname or ""
    # Escaped as it stands, as `nsIURL.fileName` hands it back.
    directories, _, name = parts.path.rpartition("/")
    return name or directories.rpartition("/")[2]


async def _parent_key(
    session: AsyncSession, library: Library, key: str, access: auth.Access, *, child: str
) -> str:
    """The key of the item a new child is made under, if it may have one.

    Asked here before `save_item` asks its own, wider question, so that the
    browser's answers are the browser's: a child goes under a regular item its
    list shows, and a refusal is a 400 rather than the sync protocol's 409.
    """
    parent = await items_service.get_item(session, library, key, permit=access)
    if parent.parent_id is not None or parent.item_type in itemwrites.NOTE_BEARING_TYPES:
        raise InvalidInputError(f"{child.capitalize()} can be added only to a regular item")
    if parent.deleted:
        raise InvalidInputError(f"Restore the item from the trash to add {child} to it")
    return parent.key


#: The link modes whose file lives here, and so can be put here.
#:
#: Not ``embedded_image``, which is a note's picture and is written by whatever
#: wrote the note; and not a linked file, whose bytes are on somebody's own disk.
REPLACEABLE_LINK_MODES = frozenset({"imported_file", "imported_url"})


def _mtime(value: int | None) -> int:
    """The file's modification time in milliseconds, as the desktop records it.

    A browser reads it off the file it was handed. A sender that has none is
    putting the file here now, so now is when it was last changed as far as
    this library knows.
    """
    return value if value is not None else int(time.time() * 1000)


def _not_a_form(request: Request) -> None:
    """Refuse a body that is a form rather than the file itself.

    Stored as it came, a form's boundaries and part headers would become the
    attachment -- a file every client downloads and none can open.
    """
    if request.headers.get("Content-Type", "").lower().startswith("multipart/"):
        raise InvalidInputError("Send the file itself as the request body, not a form")


def _declared_too_large(request: Request, limit: int) -> None:
    """Refuse an upload whose declared length is over the limit, before a byte is read."""
    declared = request.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > limit:
        raise RequestTooLargeError("File is too large")


async def _let_go(session: AsyncSession) -> None:
    """End the transaction before the body is read, and forget what it read.

    Nothing is held open while a file arrives, which may take minutes. And
    nothing read before is believed after: the session keeps what it loaded,
    so an item asked for again under the lock would come back as it was before
    the upload began -- with the digest another replacement has since moved
    on from -- rather than as it is.
    """
    await session.commit()
    session.expunge_all()


async def _body(request: Request) -> AsyncIterator[bytes]:
    async for chunk in request.stream():
        if chunk:
            yield chunk


@router.post("/libraries/{library_id}/attachments", status_code=201)
async def upload_attachment(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    limit: UploadLimitDep,
    library_id: int,
    _csrf: CsrfDep,
    filename: Annotated[str, Query()],
    parent_item: Annotated[str | None, Query(alias="parentItem")] = None,
    collections: Annotated[list[str] | None, Query()] = None,
    title: Annotated[str | None, Query()] = None,
    mtime: Annotated[int | None, Query()] = None,
) -> Response:
    """Make an attachment holding the file that is the request body.

    One request rather than the v3 three, because the browser has the file in
    hand and nothing to negotiate: there is no digest to check against a
    promise and no client deciding whether to send at all. What is left of
    the protocol is what made it safe. Every permission is asked before a byte
    is read -- the library, the group's ``fileEditing`` policy, the parent --
    and again under the lock afterwards; the bytes are hashed on their way into
    the store and moved into place whole; and the attachment is written once,
    at one new library version, already describing them. So a desktop syncing
    afterwards finds what its own upload would have left: an ``imported_file``
    whose ``md5``, ``mtime`` and ``filename`` it can download.

    The body is the file, not a form: a form's parser spools a file part to
    disk before anything can read it, which would be every upload written
    twice. Its ``Content-Type`` is the file's. ``title`` is the browser's,
    because the desktop's default for a first PDF or image under an item is a
    word in the language of whoever adds it; without one the file is named
    after itself, which is the desktop's own fallback.
    """
    library, access = await _library(session, user, library_id, write=True)
    await auth.require_user_file_write(session, library, user.id, access)
    _not_a_form(request)
    if parent_item is not None and collections:
        # A child is in its parent's collections and nowhere else of its own,
        # which is why the desktop refuses to be given both.
        raise InvalidInputError("An attachment under an item cannot be filed as well")
    if parent_item is not None:
        await _parent_key(session, library, parent_item, access, child="a file")
    _declared_too_large(request, limit)
    await _let_go(session)

    root = Path(request.app.state.settings.storage_path)
    md5, _ = await storage.receive_bytes(root, _body(request), limit=limit)

    name = storage.valid_file_name(filename)
    content_type, charset = storage.describe_file(request.headers.get("Content-Type"), name)
    payload = get_schema().template("attachment", "imported_file")
    payload.update(
        {
            "title": title.strip() if title and title.strip() else _title_from(name),
            "filename": name,
            "contentType": content_type,
            "charset": charset,
            "md5": md5,
            "mtime": _mtime(mtime),
        }
    )
    if collections:
        payload["collections"] = list(dict.fromkeys(collections))

    library = await writes.lock_library(session, library)
    # Asked again: the parent may have gone to the trash while the file came.
    access = await auth.user_access(session, library, user.id)
    await auth.require_user_file_write(session, library, user.id, access)
    if parent_item is not None:
        payload["parentItem"] = await _parent_key(
            session, library, parent_item, access, child="a file"
        )

    version = await writes.bump_library_version(session, library)
    try:
        item = await itemwrites.save_item(
            session, library, payload, version, actor_id=user.id, permit=access
        )
    except MissingObjectError as missing:
        # A collection gone since the page loaded, as for any new item.
        raise NotFoundError(missing.message) from None
    assert item is not None
    # The bytes just sent are what downloads serve; see `Item.registered_md5`.
    item.registered_md5 = md5
    item.registered_zip = False
    await session.flush()

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

    return JSONResponse(rendered, status_code=201, headers=library_headers(version))


def _title_from(filename: str) -> str:
    """The desktop's title for a file with no better one: its name, less the extension."""
    return re.sub(r"\.[^.]+$", "", filename)


@router.put("/libraries/{library_id}/items/{item_key}/file")
async def replace_file(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    limit: UploadLimitDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    filename: Annotated[str, Query()],
    mtime: Annotated[int | None, Query()] = None,
) -> Response:
    """Put the file that is the request body on an attachment, in place of its own.

    The precondition is the v3 upload's rather than the item's version:
    ``If-Match`` names the digest being replaced, or ``If-None-Match: *`` says
    there are no bytes here to replace. What is at stake is overwriting a file
    another client replaced meanwhile, and a tag added to the attachment since
    the page loaded is not that.

    The attachment takes the new file's name, type and digest, as a desktop's
    upload of a changed file gives it, and keeps its title: a title is what
    somebody called the attachment, not the file.
    """
    library, access = await _library(session, user, library_id, write=True)
    await auth.require_user_file_write(session, library, user.id, access)
    _not_a_form(request)
    root = Path(request.app.state.settings.storage_path)
    item = await items_service.get_item(session, library, item_key, permit=access)
    _replaceable(item, access, request, root)
    _declared_too_large(request, limit)
    await _let_go(session)

    md5, _ = await storage.receive_bytes(root, _body(request), limit=limit)
    name = storage.valid_file_name(filename)
    content_type, charset = storage.describe_file(request.headers.get("Content-Type"), name)

    library = await writes.lock_library(session, library)
    access = await auth.user_access(session, library, user.id)
    await auth.require_user_file_write(session, library, user.id, access)
    item = await items_service.get_item(session, library, item_key, permit=access)
    # Asked again under the lock, which is the answer that counts: a second
    # replacement that finished while these bytes came has moved the digest.
    _replaceable(item, access, request, root)

    version = await writes.bump_library_version(session, library)
    await itemwrites.save_item(
        session,
        library,
        {
            "filename": name,
            "contentType": content_type,
            "charset": charset,
            "md5": md5,
            "mtime": _mtime(mtime),
        },
        version,
        key=item.key,
        replace=False,
        actor_id=user.id,
        permit=access,
        stored=item,
    )
    item.registered_md5 = md5
    item.registered_zip = False

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


def _replaceable(item: Item, access: auth.Access, request: Request, root: Path) -> None:
    """Refuse unless this attachment's file is here to replace, by this person, now."""
    if item.item_type != "attachment":
        raise InvalidInputError("Only an attachment holds a file")
    if item.field_values().get("linkMode") not in REPLACEABLE_LINK_MODES:
        raise InvalidInputError("This attachment's file is not stored here")
    if item.deleted:
        raise InvalidInputError("Restore the attachment from the trash to change it")
    access.require_change(item.created_by_user_id)
    storage.check_preconditions(
        item, request.headers.get("If-Match"), request.headers.get("If-None-Match"), root
    )


@router.patch("/libraries/{library_id}/items/{item_key}")
async def update_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    body: Annotated[ItemEdit, Body()],
) -> Response:
    """Edit one item: fields, creators, tags, relations or its note.

    The one write here that names a single item in its path, and the one that
    states the version it replaces. Every other change is an add-and-remove
    errand the server works out for itself against what is stored, so a stale
    page cannot express a wrong one; text is different. Somebody typing over a
    title that another client changed while the page sat open is a lost write,
    and the browser knows which version it was shown. A version belongs to an
    item, which is why this is not something a selection can ask for.

    An edit that changes nothing -- a field left the way it was on blur --
    answers with the item as it stands and takes no version, as the v3 batch
    reports it unchanged: every syncing client would otherwise fetch an item to
    find nothing different.
    """
    library, access = await _library(session, user, library_id, write=True)
    patch = body.patch()

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    if body.version is None:
        raise PreconditionRequiredError("Say which version you are changing")
    if body.version != item.version:
        raise PreconditionFailedError("The item has changed since you read it")
    if item.deleted:
        # The desktop draws the trash read-only, and an edit there would be a
        # change nobody can see until the item is restored.
        raise InvalidInputError("Restore the item from the trash to change it")
    if body.item_type is not None:
        patch = _retyped(item, body.item_type, body.discard)
    if "filename" in patch:
        patch = _renamed(item, patch)

    previous_version = library.version
    version = await writes.bump_library_version(session, library)

    # Through `save_item`, which is what decides whether a field belongs to
    # this item type at all -- a book has no note and a note has no `rights` --
    # and the refusal for that is the one a syncing client would get, from the
    # same place. It also derives the sort keys and asks `permit` whether this
    # member may change this item.
    written = await itemwrites.save_item(
        session,
        library,
        patch,
        version,
        key=item.key,
        replace=False,
        detect_unchanged=True,
        actor_id=user.id,
        permit=access,
        stored=item,
    )
    if written is None:
        # Everything the session held is expired by the rollback, so the
        # library is read again by its id rather than off an expired object.
        await session.rollback()
        library = await session.get(Library, library_id)
        assert library is not None
        item = await items_service.get_item(session, library, item_key)
        rendered = await _rendered(session, item, library, base_url)
        return JSONResponse(rendered, headers=library_headers(previous_version))

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


@router.post("/libraries/{library_id}/items/{item_key}/related")
async def relate_items(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    _csrf: CsrfDep,
    body: Annotated[RelatedItems, Body()],
) -> Response:
    """Relate one item to others, each naming the other: the Related section's *Add*."""
    return await _relink(session, user, base_url, library_id, item_key, body.items, adding=True)


@router.delete("/libraries/{library_id}/items/{item_key}/related/{other_key}")
async def unrelate_items(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
    other_key: str,
    _csrf: CsrfDep,
) -> Response:
    """Take a related-items link off both items: the Related section's *Remove*."""
    return await _relink(session, user, base_url, library_id, item_key, [other_key], adding=False)


async def _relink(
    session: AsyncSession,
    user: User,
    base_url: str,
    library_id: int,
    item_key: str,
    others: list[str],
    *,
    adding: bool,
) -> Response:
    """Add or remove `dc:relation` on both sides, as the desktop's related box does.

    `Zotero.Item.addRelatedItem` writes one side; the box calls it on each item
    and saves both with `skipDateModifiedUpdate`, so relating is not editing:
    each item restates the `dateModified` it has, and nobody becomes its last
    modifier. The library takes one version for the lot, and none when every
    link asked for is already there, or already gone.
    """
    library, access = await _library(session, user, library_id, write=True)
    library = await writes.lock_library(session, library)
    previous_version = library.version

    keys = list(dict.fromkeys(others))
    if item_key in keys:
        raise InvalidInputError("An item cannot be related to itself")
    item = await items_service.get_item(session, library, item_key, permit=access)
    partners = await items_service.get_items(session, library, keys, permit=access)
    everyone = [item, *partners]
    if any(each.deleted for each in everyone):
        raise InvalidInputError("Restore the item from the trash to relate it")

    links = {(item.id, partner.id) for partner in partners}
    links |= {(partner.id, item.id) for partner in partners}
    by_id = {each.id: each for each in everyone}
    wanted: dict[int, list[tuple[str, str]]] = {}
    for each in everyone:
        stored = [(relation.predicate, relation.object) for relation in each.relations]
        named = {
            (items_service.RELATED, items_service.item_uri(library, by_id[other].key))
            for subject, other in links
            if subject == each.id
        }
        if adding:
            pairs = stored + [pair for pair in sorted(named) if pair not in stored]
        else:
            pairs = [pair for pair in stored if pair not in named]
        if pairs != stored:
            wanted[each.id] = pairs

    if not wanted:
        # Nothing to write, and the lock was the only statement: let it go
        # without a version, and answer with the items as they stand.
        await session.rollback()
        library = await session.get(Library, library_id)
        assert library is not None
        everyone = await items_service.get_items(session, library, [item_key, *keys])
        rendered = await _rendered_all(session, everyone, library, base_url)
        return JSONResponse({"items": rendered}, headers=library_headers(previous_version))

    version = await writes.bump_library_version(session, library)
    for item_id, pairs in wanted.items():
        each = by_id[item_id]
        relations: dict[str, list[str]] = {}
        for predicate, obj in pairs:
            relations.setdefault(predicate, []).append(obj)
        await itemwrites.save_item(
            session,
            library,
            {
                "relations": relations,
                "dateModified": each.date_modified.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            version,
            key=each.key,
            replace=False,
            permit=access,
            stored=each,
        )

    rendered = await _rendered_all(session, everyone, library, base_url)
    await groupactivity.record(
        session,
        library,
        actor_id=user.id,
        kind=ActivityKind.ITEMS_CHANGED,
        count=len(wanted),
        objects=await groupactivity.name_items(
            session, library, [by_id[item_id].key for item_id in wanted]
        ),
    )
    await session.commit()
    return JSONResponse({"items": rendered}, headers=library_headers(version))


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
    library, access = await _library(session, user, library_id, write=True)

    keys = list(dict.fromkeys(key for key in item_key.split(",") if key))
    if not keys:
        raise InvalidInputError("'itemKey' parameter not provided")

    library = await writes.lock_library(session, library)
    for item in await items_service.get_items(session, library, keys):
        if not item.deleted:
            raise InvalidInputError("Move the item to the trash before deleting it")

    # Named before they go: there is nothing left to read afterwards.
    named = await groupactivity.name_items(session, library, keys)
    version = await writes.bump_library_version(session, library)
    await itemwrites.delete_items(session, library, keys, version, permit=access)
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
    library, access = await _library(session, user, library_id, write=True)

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
    await itemwrites.delete_items(session, library, trashed, version, permit=access)
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
    source, source_access = await _library(session, user, library_id, write=False)

    keys = list(dict.fromkeys(body.items))
    items = [
        await items_service.get_item(session, source, key, permit=source_access) for key in keys
    ]

    if body.library == library_id:
        raise InvalidInputError("An item is already in its own library")
    target, _ = await _library(session, user, body.library, write=True)

    target = await writes.lock_library(session, target)
    _, files_writable = (await auth.user_rights(session, [target], user.id))[target.id]
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
            include_files=source_access.files,
            files_writable=files_writable,
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
    library, _ = await _library(session, user, library_id, write=True)

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
    library, _ = await _library(session, user, library_id, write=True)

    library = await writes.lock_library(session, library)
    item = await items_service.get_item(session, library, item_key)

    version = await writes.bump_library_version(session, library)
    await publications.remove_from_publications(session, library, item, version, actor_id=user.id)

    rendered = await _rendered(session, item, library, base_url)
    await session.commit()

    return JSONResponse(rendered, headers=library_headers(version))
