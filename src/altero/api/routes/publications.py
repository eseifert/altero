"""My Publications, the public view of one person's library.

Read without a key: that is the whole point of it, and upstream's own test
suite runs the file anonymously and expects 200. Only items flagged
``inPublications`` are visible, and only through ``items`` -- upstream answers
404 for ``publications/collections`` and ``publications/searches``.

There is no group form. My Publications belongs to a person, which is also why
``inPublications`` is refused on a group item in the first place.
"""

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response

from altero.api.deps import BaseUrlDep, LibraryDep, SessionDep
from altero.api.responses import not_modified, object_response
from altero.api.routes.items import render_item, render_listing
from altero.errors import ForbiddenError, NotFoundError
from altero.services import items as items_service
from altero.services.items import Scope

router = APIRouter(tags=["publications"])


@router.get("/users/{user_id}/publications/items")
async def list_published_items(
    request: Request, session: SessionDep, library: LibraryDep, base_url: BaseUrlDep
) -> Response:
    """List the items the owner has published, to anyone who asks."""
    return await render_listing(request, session, library, base_url, Scope.PUBLICATIONS)


@router.get("/users/{user_id}/publications/items/top")
async def list_top_published_items(
    request: Request, session: SessionDep, library: LibraryDep, base_url: BaseUrlDep
) -> Response:
    return await render_listing(request, session, library, base_url, Scope.PUBLICATIONS_TOP)


@router.get("/users/{user_id}/publications/items/{item_key}")
async def get_published_item(
    item_key: str,
    request: Request,
    session: SessionDep,
    library: LibraryDep,
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


@router.post("/users/{user_id}/publications/items")
@router.put("/users/{user_id}/publications/items")
@router.delete("/users/{user_id}/publications/items")
async def refuse_writes(library: LibraryDep) -> Response:
    """Refuse writes through this view.

    The list is public to read, not to add to. Items reach it by being written
    to the library with ``inPublications`` set.
    """
    raise ForbiddenError("Cannot write to My Publications")
