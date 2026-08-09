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

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import ApiKeyDep, BaseUrlDep, LibraryDep, SessionDep
from altero.api.responses import library_headers, not_modified, object_response
from altero.api.routes.items import render_item, render_listing
from altero.errors import ForbiddenError, NotFoundError
from altero.models import Library
from altero.services import items as items_service
from altero.services import profiles
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


@router.get("/users/{user_id}/publications/items")
async def list_published_items(
    request: Request, session: SessionDep, library: VisibleLibraryDep, base_url: BaseUrlDep
) -> Response:
    """List the items the owner has published, to anyone who asks."""
    return await render_listing(request, session, library, base_url, Scope.PUBLICATIONS)


@router.get("/users/{user_id}/publications/items/top")
async def list_top_published_items(
    request: Request, session: SessionDep, library: VisibleLibraryDep, base_url: BaseUrlDep
) -> Response:
    return await render_listing(request, session, library, base_url, Scope.PUBLICATIONS_TOP)


@router.get("/users/{user_id}/publications/items/{item_key}")
async def get_published_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: VisibleLibraryDep,
    base_url: BaseUrlDep,
) -> Response:
    """Return one published item.

    An item that is not published is reported as absent rather than refused:
    hiding it from the listing would be pointless if its key still fetched it.
    """
    if (response := not_modified(request, library.version)) is not None:
        return response

    item = await items_service.get_item(session, library, item_key)
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
