"""My Publications, the public view of one person's library.

Read without a key: that is the whole point of it, and upstream's own test
suite runs the file anonymously and expects 200. Only items flagged
``inPublications`` are visible, and only through ``items`` -- upstream answers
404 for ``publications/collections`` and ``publications/searches``.

There is no group form. My Publications belongs to a person, which is also why
``inPublications`` is refused on a group item in the first place.

One thing here is altero's and not upstream's: the owner decides who this list
is for. The default is ``public``, which is exactly the behaviour above, so an
account that never opens the setting is served precisely as the dataserver
serves one. See :func:`get_visible_library` and
:mod:`altero.services.profiles`.
"""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import AccessDep, ApiKeyDep, BaseUrlDep, LibraryDep, SessionDep
from altero.api.responses import library_headers, not_modified, object_response
from altero.api.routes.items import render_item, render_listing
from altero.errors import ForbiddenError, NotFoundError
from altero.models import Library
from altero.services import auth, profiles
from altero.services import items as items_service
from altero.services.items import Scope

router = APIRouter(tags=["publications"])


async def get_visible_library(
    library: LibraryDep, api_key: ApiKeyDep, session: SessionDep
) -> Library:
    """Return the addressed library, if its owner publishes to this caller.

    Nothing is asked of the caller when the owner's setting is ``public``,
    which is the default and upstream's only behaviour: the whole point of
    these endpoints is that they answer without a key, and upstream's own test
    file reads every one of them with ``API::useAPIKey("")``.

    The other two settings are altero's, and are enforced here rather than only
    on the profile page. A page in the browser that refused a stranger while
    ``curl /users/1/publications/items`` still listed the same work would not
    be a setting; it would be a decoration.
    """
    if not await profiles.readable_by_key(session, library, api_key):
        raise ForbiddenError("These publications are not public")
    return library


VisibleLibraryDep = Annotated[Library, Depends(get_visible_library)]


def published_permit(access: auth.Access) -> auth.Access:
    """Return what a caller may read *of My Publications*.

    The confinement a resource-scoped OAuth grant carries, and nothing else.
    The notes narrowing is deliberately dropped, and it has to be: these
    endpoints answer with no credential at all, so an :class:`Access` computed
    for the library says ``notes=library.public`` for an anonymous caller --
    which for the ordinary private library is ``False``, and would take every
    published note out of the public view.

    It is the same rule ``_may_read_notes`` already applies from the other
    side: what has been published is published, and withholding it from a
    credential that could have it by presenting nothing at all would be theatre
    rather than a permission. Found by ``test_publications_endpoints.py``, whose
    anonymous ``format=versions`` read lost a published child note.
    """
    return replace(access, notes=True)


@router.get("/users/{user_id}/publications/items")
async def list_published_items(
    request: Request,
    session: SessionDep,
    library: VisibleLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    """List the items the owner has published, to anyone who asks.

    ``permit`` reaches here too, which matters only for a resource-scoped OAuth
    token: an anonymous caller carries no confinement, so the public view is
    exactly what it was. A confined token sees the published items inside its
    grant -- which is not the whole of what a public reader sees, and is the
    right way round. An application asking for less than a stranger gets is not
    a leak; the reverse would be.
    """
    return await render_listing(
        request, session, library, base_url, Scope.PUBLICATIONS, permit=published_permit(access)
    )


@router.get("/users/{user_id}/publications/items/top")
async def list_top_published_items(
    request: Request,
    session: SessionDep,
    library: VisibleLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    return await render_listing(
        request, session, library, base_url, Scope.PUBLICATIONS_TOP, permit=published_permit(access)
    )


@router.get("/users/{user_id}/publications/items/{item_key}")
async def get_published_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: VisibleLibraryDep,
    access: AccessDep,
    base_url: BaseUrlDep,
) -> Response:
    """Return one published item.

    An item that is not published is reported as absent rather than refused:
    hiding it from the listing would be pointless if its key still fetched it.
    """
    if (response := not_modified(request, library.version)) is not None:
        return response

    item = await items_service.get_item(session, library, item_key, permit=published_permit(access))
    if not item.in_publications:
        raise NotFoundError("Item does not exist")

    return object_response(await render_item(session, item, library, base_url), library.version)


@router.get("/users/{user_id}/publications/settings")
async def list_published_settings(library: VisibleLibraryDep) -> Response:
    """Answer the settings poll a My Publications sync makes.

    Always empty. Upstream serves an empty array here too: settings belong to a
    library, and My Publications is a view of one rather than a library of its
    own. The client asks anyway, as part of the same cycle it runs for a real
    library, and treats anything but a 200 as a failed sync.
    """
    return JSONResponse([], headers=library_headers(library.version, total=0))


@router.get("/users/{user_id}/publications/deleted")
async def list_published_deletions(library: VisibleLibraryDep) -> Response:
    """Answer the deletion poll, which is likewise always empty.

    An object leaves My Publications by having ``inPublications`` cleared, which
    the client sees as a change to the item. Nothing is ever deleted *from* the
    view, so there is nothing to report.
    """
    return JSONResponse({}, headers=library_headers(library.version))


@router.post("/users/{user_id}/publications/items")
@router.put("/users/{user_id}/publications/items")
@router.delete("/users/{user_id}/publications/items")
async def refuse_writes(library: LibraryDep) -> Response:
    """Refuse writes through this view.

    The list is public to read, not to add to. Items reach it by being written
    to the library with ``inPublications`` set.
    """
    raise ForbiddenError("Cannot write to My Publications")
