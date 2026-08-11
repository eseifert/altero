"""Reading libraries from the web interface.

The v3 API already lists items, but only to an API key, and a session cookie is
deliberately not accepted there. So the browser gets its own read endpoints
here, over the same services and the same serialiser: the shape of an item is
identical to what a sync client receives, and there is one implementation of
what an item *is*.

Access is decided by :mod:`altero.services.auth` exactly as it is for a key.
The credential differs; the rules do not.
"""

import shutil
import tempfile
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from altero import cite, serializers
from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.responses import CONTENT_TYPES
from altero.api.routes.web import CurrentUserDep
from altero.itemschema import get_schema
from altero.models import Item, Library, LibraryType
from altero.query import (
    ITEM_SORT_FIELDS,
    Direction,
    Format,
    ListQuery,
    QuickSearchMode,
    TagSearchMode,
    default_direction,
)
from altero.search import parse_expressions
from altero.services import auth, collections, itemexport, items, storage, tags

router = APIRouter(prefix="/web", tags=["web"])

#: Largest page the interface will ask for at once.
MAX_LIMIT = 100

#: Collections and tags are drawn whole rather than paged, so both have a cap
#: that is high enough not to be reached by a real library and low enough that
#: a pathological one cannot exhaust memory.
MAX_COLLECTIONS = 5000
MAX_TAGS = 5000


class Scope(StrEnum):
    """What the sidebar has selected."""

    TOP = "top"
    ALL = "all"
    TRASH = "trash"
    #: My Publications, which a personal library has and a group does not.
    PUBLICATIONS = "publications"
    #: The three the desktop client works out for itself. None is in the v3
    #: API; see `docs/compatibility.md` for what altero decided each one means.
    UNFILED = "unfiled"
    DUPLICATES = "duplicates"
    RECENTLY_READ = "recentlyread"


#: The service-level scope each of those means outside a collection.
_SCOPES = {
    Scope.TOP: items.Scope.TOP,
    Scope.ALL: items.Scope.ALL,
    Scope.TRASH: items.Scope.TRASH,
    Scope.PUBLICATIONS: items.Scope.PUBLICATIONS_TOP,
    Scope.UNFILED: items.Scope.UNFILED,
    Scope.DUPLICATES: items.Scope.DUPLICATES,
    Scope.RECENTLY_READ: items.Scope.RECENTLY_READ,
}


async def _readable_library(session: SessionDep, user: CurrentUserDep, library_id: int) -> Library:
    """Return the library if this user may read it.

    Resolved from the numeric library id rather than a ``/users/{id}`` prefix,
    because the interface holds a flat list of what the person can see and does
    not care which kind each one is.
    """
    library = await session.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="No such library")

    if not (await auth.user_access(session, library, user.id)).read:
        raise HTTPException(status_code=403, detail="You cannot read this library")
    return library


@router.get("/libraries")
async def list_libraries(
    session: SessionDep, user: CurrentUserDep, base_url: BaseUrlDep
) -> Response:
    """Return every library this user can open, personal first."""
    from altero.models import GroupMember

    personal = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == user.id)
    )

    group_ids = await session.scalars(
        select(GroupMember.library_id).where(GroupMember.user_id == user.id)
    )
    groups = list(await session.scalars(select(Library).where(Library.id.in_(list(group_ids)))))

    visible = ([personal] if personal is not None else []) + groups
    return JSONResponse(
        [
            {
                "id": library.id,
                "type": library.type.value,
                "ownerId": library.owner_id,
                "name": library.name,
                "version": library.version,
                "prefix": serializers.library_prefix(library),
                # Whether this account may change the library, resolved here
                # rather than guessed in the browser. A group can reserve
                # editing for its administrators, and a screen that offered the
                # controls anyway would be a second implementation of that rule
                # drifting against the one that actually refuses the request.
                "writable": (await auth.user_access(session, library, user.id)).write,
            }
            for library in visible
        ]
    )


async def render_items(
    session: SessionDep,
    objects: Sequence[Item],
    library: Library,
    base_url: str,
) -> list[dict[str, Any]]:
    """Serialize items with the related data their envelopes carry.

    Shared with :mod:`altero.api.routes.webprofile`, so that an item read on a
    profile page is the same object the library view shows and the sync
    protocol writes. There is one definition of an item in this application.

    Gathered once for the whole page, as the v3 item route does, so a page of a
    hundred items is a handful of queries rather than hundreds.
    """
    children = await items.count_children(session, objects)
    collections = await items.collection_keys_for(session, objects)
    tags = await items.tags_for(session, objects)
    parents = await items.parent_keys_for(session, objects)

    return [
        serializers.item(
            obj,
            library,
            base_url,
            tags=tags.get(obj.id, []),
            collections=collections.get(obj.id, []),
            num_children=children.get(obj.id, 0),
            parent_key=parents.get(obj.parent_id) if obj.parent_id else None,
        )
        for obj in objects
    ]


def _item_query(
    library: Library,
    *,
    scope: Scope,
    collection: str | None,
    q: str | None,
    sort: str,
    direction: Direction | None,
    tag: Sequence[str] | None,
    item_keys: Sequence[str] = (),
    limit: int = 50,
    start: int = 0,
) -> tuple[ListQuery, items.Scope]:
    """Return the query and the service-level scope one view of a library means.

    Shared by the listing and the export, because an export that quietly meant
    something else than the list it was started from would be the one file
    nobody can check: what comes out has to be what was on screen.
    """
    if sort not in ITEM_SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Cannot sort by {sort}")

    if scope is Scope.PUBLICATIONS and library.type is not LibraryType.USER:
        # A group has no My Publications: publishing is something an account
        # does with its own library. The sidebar does not offer the row, so
        # this is only reachable by hand.
        raise HTTPException(status_code=400, detail="Only a personal library has publications")

    item_scope = _SCOPES[scope]
    if collection:
        item_scope = items.Scope.COLLECTION_TOP if scope is Scope.TOP else items.Scope.COLLECTION

    query = ListQuery(
        limit=limit,
        start=start,
        q=q,
        qmode=QuickSearchMode.EVERYTHING if q else QuickSearchMode.TITLE_CREATOR_YEAR,
        sort=sort,
        direction=direction or default_direction(sort),
        tags=parse_expressions(tag or []),
        item_keys=tuple(item_keys),
    )
    return query, item_scope


@router.get("/libraries/{library_id}/items")
async def list_library_items(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    start: Annotated[int, Query(ge=0)] = 0,
    q: str | None = None,
    sort: str = "dateModified",
    direction: Direction | None = None,
    collection: str | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    scope: Scope = Scope.TOP,
) -> Response:
    """Return one page of items, in the v3 API's own item shape.

    The scope is what the sidebar selects: the top level, everything including
    child notes and attachments, the trash, My Publications, or one of the
    three views the desktop client offers beside the collections — unfiled
    items, duplicates, and what has been read lately. A collection narrows it
    to that collection's own top-level items, which is what the desktop client
    shows when you click one.
    """
    library = await _readable_library(session, user, library_id)

    query, item_scope = _item_query(
        library,
        scope=scope,
        collection=collection,
        q=q,
        sort=sort,
        direction=direction,
        tag=tag,
        limit=limit,
        start=start,
    )
    page = await items.list_items(session, library, query, scope=item_scope, key=collection)

    return JSONResponse(
        {
            "total": page.total,
            "libraryVersion": page.library_version,
            "items": await render_items(session, page.objects, library, base_url),
        }
    )


#: Declared above ``/items/{item_key}`` on purpose: routes are matched in the
#: order they are added, and an export is not an item with the key "export".
@router.get("/libraries/{library_id}/items/export")
async def export_library_items(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    response_format: Annotated[str, Query(alias="format")] = str(Format.BIBTEX),
    name: str | None = None,
    q: str | None = None,
    sort: str = "dateModified",
    direction: Direction | None = None,
    collection: str | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    item_key: Annotated[str | None, Query(alias="itemKey")] = None,
    scope: Scope = Scope.TOP,
) -> Response:
    """Write what the item list is showing as a file, and send it.

    The desktop client has three of these — Export Library…, Export Collection…
    and Export Items… — and they are one errand with three ways of saying which
    items: the whole library, a collection, or the rows picked out. So this
    takes the listing's own parameters, and ``itemKey`` narrows them to a
    selection; whatever the list would draw is what the file holds.

    Reading the library is enough. An archive is an administrator's affair
    because it carries every version, the deletion log and the attachment bytes;
    this carries the bibliography of items the reader can already open one by
    one, which is the same reason ``/citation`` beside it needs no more.

    Built on disk and streamed from there, as the archive is: a library's worth
    of BibTeX is not something to assemble in memory per request. The temporary
    copy goes once the response has been sent.
    """
    library = await _readable_library(session, user, library_id)

    offered = sorted(str(entry) for entry in itemexport.EXPORT_FORMATS)
    if response_format not in offered:
        # `json` and `atom` are refused here as firmly as a made-up name: they
        # describe an item to a program that already knows what an item is,
        # which is the API's job and not a file anybody exports.
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export as {response_format}; the formats are {', '.join(offered)}",
        )
    chosen = Format(response_format)

    query, item_scope = _item_query(
        library,
        scope=scope,
        collection=collection,
        q=q,
        sort=sort,
        direction=direction,
        tag=tag,
        item_keys=[key for key in (item_key or "").split(",") if key],
    )

    workspace = Path(tempfile.mkdtemp(prefix="altero-items-"))
    filename = itemexport.file_name(
        name, chosen, fallback=f"altero-{library.type.value}-{library.owner_id}"
    )
    try:
        await itemexport.write_items(
            session,
            library,
            workspace / filename,
            response_format=chosen,
            query=query,
            scope=item_scope,
            key=collection,
        )
    except BaseException:
        shutil.rmtree(workspace, ignore_errors=True)
        raise

    return FileResponse(
        workspace / filename,
        media_type=CONTENT_TYPES[chosen],
        filename=filename,
        background=BackgroundTask(shutil.rmtree, workspace, ignore_errors=True),
    )


@router.get("/libraries/{library_id}/items/{item_key}")
async def get_library_item(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
) -> Response:
    """Return one item, for the detail pane."""
    library = await _readable_library(session, user, library_id)
    item = await items.get_item(session, library, item_key)

    (rendered,) = await render_items(session, [item], library, base_url)
    return JSONResponse(rendered)


@router.get("/libraries/{library_id}/items/{item_key}/children")
async def list_item_children(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    item_key: str,
) -> Response:
    """Return an item's notes and attachments, in the order the client shows them."""
    library = await _readable_library(session, user, library_id)
    await items.get_item(session, library, item_key)

    query = ListQuery(limit=MAX_LIMIT, sort="title", direction=Direction.ASCENDING)
    page = await items.list_items(session, library, query, scope=items.Scope.CHILDREN, key=item_key)

    return JSONResponse(
        {
            "total": page.total,
            "items": await render_items(session, page.objects, library, base_url),
        }
    )


@router.get("/libraries/{library_id}/items/{item_key}/file")
async def download_item_file(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    item_key: str,
    download: bool = False,
) -> Response:
    """Return an attachment's bytes.

    Served here rather than by redirecting to the v3 file endpoint, which would
    need an API key. ``download`` chooses between showing the file in the
    browser and saving it, which is the difference between reading a PDF and
    filing it away.
    """
    library = await _readable_library(session, user, library_id)
    item = await items.get_item(session, library, item_key)
    path, fields = await storage.stored_file(item, Path(request.app.state.settings.storage_path))

    content_type = fields.get("contentType") or "application/octet-stream"
    if not download and (charset := fields.get("charset")):
        content_type = f"{content_type}; charset={charset}"

    return FileResponse(
        path,
        media_type=content_type,
        filename=(fields.get("filename") or item.key) if download else None,
    )


@router.get("/libraries/{library_id}/collections")
async def list_library_collections(
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
) -> Response:
    """Return every collection in the library, for the sidebar's tree.

    The whole tree at once rather than a page of it: the browser draws it as one
    structure, and a library with enough collections to page through would be
    remarkable.
    """
    library = await _readable_library(session, user, library_id)

    query = ListQuery(limit=MAX_COLLECTIONS, sort="title", direction=Direction.ASCENDING)
    page = await collections.list_collections(session, library, query)

    subcollections = await collections.count_subcollections(session, page.objects)
    counts = await collections.count_items(session, page.objects)
    parents = await collections.parent_keys_for(session, page.objects)

    return JSONResponse(
        {
            "total": page.total,
            "collections": [
                serializers.collection(
                    obj,
                    library,
                    base_url,
                    num_collections=subcollections.get(obj.id, 0),
                    num_items=counts.get(obj.id, 0),
                    parent_key=parents.get(obj.parent_id) if obj.parent_id else None,
                )
                for obj in page.objects
            ],
        }
    )


@router.get("/libraries/{library_id}/items/{item_key}/citation")
async def render_item_citation(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    item_key: str,
    style: str = cite.DEFAULT_STYLE,
    locale: str = cite.DEFAULT_LOCALE,
) -> Response:
    """Return one item as a bibliography entry and an in-text citation.

    The same renderer the v3 API's `format=bib` uses, reached with a cookie
    instead of a key. Producing a citation in the browser instead would mean a
    second CSL implementation, in a second language, disagreeing with the first.
    """
    library = await _readable_library(session, user, library_id)
    item = await items.get_item(session, library, item_key)

    csl = cite.csl_item(item, library)
    return JSONResponse(
        {
            "bib": cite.bibliography([csl], style=style, locale=locale),
            "citation": cite.citation(csl, style=style, locale=locale),
        }
    )


@router.get("/schema")
async def get_display_names(locale: str | None = None) -> Response:
    """Return the display names for item types, fields and creator types.

    Public, like the v3 schema endpoints it mirrors: the item type schema is the
    same for everyone and describes no library. It is served here so the
    interface has one origin to talk to.
    """
    return JSONResponse(get_schema().display_names(locale))


@router.get("/libraries/{library_id}/tags")
async def list_library_tags(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    limit: Annotated[int, Query(ge=1, le=MAX_TAGS)] = MAX_TAGS,
    q: str | None = None,
) -> Response:
    """Return the library's tags with their item counts, for the tag selector."""
    library = await _readable_library(session, user, library_id)

    query = ListQuery(limit=limit, q=q, qmode=TagSearchMode.CONTAINS, sort="title")
    page = await tags.list_tags(session, library, query)

    return JSONResponse(
        {
            "total": page.total,
            "tags": [
                {"tag": summary.name, "type": summary.type, "numItems": summary.num_items}
                for summary in page.objects
            ],
        }
    )
