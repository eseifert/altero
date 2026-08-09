"""Profile pages: one person's published work, read by whoever may see it.

The one part of ``/web`` that answers without a cookie. That is not a hole in
the boundary the rest of the package holds, because it is not authentication:
these endpoints identify no caller and reach nothing but items their owner
flagged ``inPublications``, which the v3 API already serves to anonymous
callers at ``/users/<id>/publications/items``. The cookie is *read* when there
is one -- see :func:`altero.api.routes.web.get_viewer` -- because an account
that limits its profile to people signed in here needs the request to say
whether this is one. It is never required and never grants anything beyond the
setting.

Everything served here goes through the same services and the same serialiser
as the library view, so an item on a profile page is the item a syncing client
receives. What differs is which items exist: :func:`profiles.published_item`
and ``Scope.PUBLICATIONS_TOP`` are the whole of it.

A profile nobody may read answers **404**, exactly as an unclaimed username
does. Distinguishing them would turn the page into a way of asking which names
have accounts behind them, and the interface can say the useful part -- that
some profiles are shown only to people signed in -- without the server
disclosing anything.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from altero import cite
from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.routes.web import ViewerDep
from altero.api.routes.weblibrary import render_items
from altero.errors import NotFoundError
from altero.models import Library, User
from altero.query import ITEM_SORT_FIELDS, Direction, ListQuery, QuickSearchMode, default_direction
from altero.services import items, profiles, storage

router = APIRouter(prefix="/web", tags=["web"])

#: Largest page of publications the interface will ask for at once, matching
#: the library view's.
MAX_LIMIT = 100

#: How a publication list is read: newest work first. The desktop client sorts
#: My Publications by whatever the item list was last sorted by; a page somebody
#: else is reading has no such memory, and a bibliography is conventionally in
#: reverse date order.
DEFAULT_SORT = "date"


async def _profile(session: SessionDep, viewer: User | None, username: str) -> tuple[User, Library]:
    """Return the account and library ``username`` names, if this viewer may.

    Raises:
        NotFoundError: if there is no such account, or if its owner has not
            made the profile visible to this viewer. One answer for both; see
            the module docstring.
    """
    owner = await profiles.find_by_username(session, username)
    if not profiles.visible_to(owner, viewer):
        raise NotFoundError("No such profile")
    return owner, await profiles.library_of(session, owner)


@router.get("/profiles/{username}")
async def read_profile(session: SessionDep, viewer: ViewerDep, username: str) -> Response:
    """Return who this page belongs to, and how much is on it."""
    owner, library = await _profile(session, viewer, username)
    reading_their_own = viewer is not None and viewer.id == owner.id

    return JSONResponse(
        {
            "username": owner.username,
            # What the person calls themselves, falling back to the username
            # the way `Zotero_Users::getName` does -- a page headed by an empty
            # string belongs to nobody.
            "displayName": owner.display_name or owner.username,
            "numPublications": await profiles.count_published(session, library),
            # So the interface can offer the owner the way to change who sees
            # this, rather than making them go and look for it. Neither field
            # ever says anything about anybody else's account.
            "owner": reading_their_own,
            "visibility": owner.profile_visibility.value if reading_their_own else None,
        }
    )


@router.get("/profiles/{username}/items")
async def list_published_items(
    session: SessionDep,
    viewer: ViewerDep,
    base_url: BaseUrlDep,
    username: str,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    start: Annotated[int, Query(ge=0)] = 0,
    q: str | None = None,
    sort: str = DEFAULT_SORT,
    direction: Direction | None = None,
) -> Response:
    """Return one page of the work this person has published."""
    _, library = await _profile(session, viewer, username)

    if sort not in ITEM_SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Cannot sort by {sort}")

    query = ListQuery(
        limit=limit,
        start=start,
        q=q,
        qmode=QuickSearchMode.EVERYTHING if q else QuickSearchMode.TITLE_CREATOR_YEAR,
        sort=sort,
        direction=direction or default_direction(sort),
    )
    page = await items.list_items(session, library, query, scope=items.Scope.PUBLICATIONS_TOP)

    return JSONResponse(
        {
            "total": page.total,
            "libraryVersion": page.library_version,
            "items": await render_items(session, page.objects, library, base_url),
        }
    )


@router.get("/profiles/{username}/items/{item_key}")
async def read_published_item(
    session: SessionDep, viewer: ViewerDep, base_url: BaseUrlDep, username: str, item_key: str
) -> Response:
    """Return one published item, for the reading pane."""
    _, library = await _profile(session, viewer, username)
    item = await profiles.published_item(session, library, item_key)

    (rendered,) = await render_items(session, [item], library, base_url)
    return JSONResponse(rendered)


@router.get("/profiles/{username}/items/{item_key}/children")
async def list_published_children(
    session: SessionDep, viewer: ViewerDep, base_url: BaseUrlDep, username: str, item_key: str
) -> Response:
    """Return the notes and files that were published with the item.

    Only those. Which children went along was answered once, by the wizard, and
    a note left behind then is not on this page now -- upstream refuses a child
    of a published item that is not itself published, in ``ItemsController``.
    """
    _, library = await _profile(session, viewer, username)
    await profiles.published_item(session, library, item_key)

    query = ListQuery(limit=MAX_LIMIT, sort="title", direction=Direction.ASCENDING)
    page = await items.list_items(session, library, query, scope=items.Scope.CHILDREN, key=item_key)
    published = [child for child in page.objects if child.in_publications]

    return JSONResponse(
        {
            "total": len(published),
            "items": await render_items(session, published, library, base_url),
        }
    )


@router.get("/profiles/{username}/items/{item_key}/file")
async def download_published_file(
    request: Request,
    session: SessionDep,
    viewer: ViewerDep,
    username: str,
    item_key: str,
    download: bool = False,
) -> Response:
    """Return a published attachment's bytes.

    This is what the licence question in the publishing wizard was about: "if
    you choose to include attached files, they will be made publicly available
    under the license you specify". Upstream serves them the same way -- the
    permission check in ``_handleFileRequest`` falls through to
    ``canAccessObject``, which returns true for a published item, under the
    comment "Check access on specific item, for My Publications files".

    The attachment has to be published itself, not merely hang off something
    that is: an item published without its files has none here.
    """
    _, library = await _profile(session, viewer, username)
    item = await profiles.published_item(session, library, item_key)

    path, fields = await storage.stored_file(item, Path(request.app.state.settings.storage_path))

    content_type = fields.get("contentType") or "application/octet-stream"
    if not download and (charset := fields.get("charset")):
        content_type = f"{content_type}; charset={charset}"

    return FileResponse(
        path,
        media_type=content_type,
        filename=(fields.get("filename") or item.key) if download else None,
    )


@router.get("/profiles/{username}/items/{item_key}/citation")
async def cite_published_item(
    session: SessionDep,
    viewer: ViewerDep,
    username: str,
    item_key: str,
    style: str = cite.DEFAULT_STYLE,
    locale: str = cite.DEFAULT_LOCALE,
) -> Response:
    """Return the item as a bibliography entry and an in-text citation.

    A list of somebody's work is the one place a reader is most likely to want
    a citation of it, and the server already renders them for the library view.
    """
    _, library = await _profile(session, viewer, username)
    item = await profiles.published_item(session, library, item_key)

    csl = cite.csl_item(item, library)
    return JSONResponse(
        {
            "bib": cite.bibliography([csl], style=style, locale=locale),
            "citation": cite.citation(csl, style=style, locale=locale),
        }
    )
