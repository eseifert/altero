"""Reading libraries from the web interface.

The v3 API already lists items, but only to an API key, and a session cookie is
deliberately not accepted there. So the browser gets its own read endpoints
here, over the same services and the same serialiser: the shape of an item is
identical to what a sync client receives, and there is one implementation of
what an item *is*.

Access is decided by :mod:`altero.services.auth` exactly as it is for a key.
The credential differs; the rules do not.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import serializers
from altero.api.deps import BaseUrlDep, SessionDep
from altero.api.routes.web import CurrentUserDep
from altero.models import Library, LibraryType, User
from altero.query import ListQuery
from altero.services import auth, items

router = APIRouter(prefix="/web", tags=["web"])

#: Largest page the interface will ask for at once.
MAX_LIMIT = 100


async def _readable_library(session: SessionDep, user: CurrentUserDep, library_id: int) -> Library:
    """Return the library if this user may read it.

    Resolved from the numeric library id rather than a ``/users/{id}`` prefix,
    because the interface holds a flat list of what the person can see and does
    not care which kind each one is.
    """
    library = await session.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="No such library")

    access = await auth.get_access(session, library, None)
    if library.type is LibraryType.USER and library.owner_id == user.id:
        return library
    if not access.read and not await _is_group_member(session, library, user):
        raise HTTPException(status_code=403, detail="You cannot read this library")
    return library


async def _is_group_member(session: SessionDep, library: Library, user: User) -> bool:
    from altero.models import GroupMember

    if library.type is not LibraryType.GROUP:
        return False
    member = await session.scalar(
        select(GroupMember).where(
            GroupMember.library_id == library.id, GroupMember.user_id == user.id
        )
    )
    return member is not None


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
            }
            for library in visible
        ]
    )


@router.get("/libraries/{library_id}/items")
async def list_library_items(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    base_url: BaseUrlDep,
    library_id: int,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    start: Annotated[int, Query(ge=0)] = 0,
    q: str | None = None,
    sort: str = "dateModified",
) -> Response:
    """Return one page of top-level items, in the v3 API's own item shape."""
    library = await _readable_library(session, user, library_id)

    query = ListQuery(limit=limit, start=start, q=q, sort=sort)
    page = await items.list_items(session, library, query, scope=items.Scope.TOP)

    children = await items.count_children(session, page.objects)
    collections = await items.collection_keys_for(session, page.objects)
    tags = await items.tags_for(session, page.objects)
    parents = await items.parent_keys_for(session, page.objects)

    return JSONResponse(
        {
            "total": page.total,
            "libraryVersion": page.library_version,
            "items": [
                serializers.item(
                    obj,
                    library,
                    base_url,
                    tags=tags.get(obj.id, []),
                    collections=collections.get(obj.id, []),
                    num_children=children.get(obj.id, 0),
                    parent_key=parents.get(obj.id),
                )
                for obj in page.objects
            ],
        }
    )
