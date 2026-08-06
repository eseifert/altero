"""Renaming a tag from the browser.

The third and last place the interface writes to the contents of a library, and
the only one of the three that reaches items. It does not reach them as items:
nothing here chooses which items to touch, adds a tag or removes one. A tag is
its name, the same name on every item carrying it, and correcting a misspelling
in a hundred of them by hand is not something a person should have to open the
desktop client for.

The rules are the ones the rest of ``/web`` follows: a cookie and never an API
key, a CSRF token, ``services/auth.user_access`` deciding who may write, and
:func:`altero.services.objectwrites.rename_tag` -- the same call the v3
endpoint makes, so a tag renamed here is renamed exactly as a syncing client
would have renamed it, down to the entry in the deletion log and the new
version on every item that carried it.
"""

from typing import Annotated

from fastapi import APIRouter, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.responses import library_headers
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import ForbiddenError, NotFoundError
from altero.models import Library, User
from altero.services import auth, objectwrites, writes
from altero.services import tags as tags_service

router = APIRouter(prefix="/web", tags=["web"])


class TagRename(BaseModel):
    """What renaming a tag takes: the name it is to have."""

    tag: str


async def _writable_library(session: AsyncSession, user: User, library_id: int) -> Library:
    """Return the library if this person may change it."""
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")

    if not (await auth.user_access(session, library, user.id)).write:
        raise ForbiddenError("You cannot change this library")
    return library


@router.patch("/libraries/{library_id}/tags/{tag_name}")
async def rename_tag(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    tag_name: str,
    _csrf: CsrfDep,
    body: Annotated[TagRename, Body()],
) -> Response:
    """Rename one tag throughout the library.

    Answers with the tag in the shape the selector already reads, so the panel
    can be redrawn from it -- though the interface asks for the list again,
    because a rename onto a name already in use leaves one tag where there were
    two and every count on the panel may have moved.

    No ``If-Unmodified-Since-Version``, for the reason the collection endpoints
    give: a sync client has a copy of the library to reconcile and must say what
    it last saw, while a person renaming the tag in front of them means that
    tag, whatever else has happened since the page was drawn.
    """
    library = await _writable_library(session, user, library_id)
    new_name = objectwrites.clean_tag_name(body.tag)

    library = await writes.lock_library(session, library)
    summary = await tags_service.get_tag(session, library, tag_name)
    if new_name == summary.name:
        # Asked for the name it already has. The client returns early on this
        # too; what was wanted is what is there, and saying so as a failure
        # would be a message about nothing.
        return JSONResponse(
            {
                "tag": summary.name,
                "type": summary.type,
                "numItems": summary.num_items,
                "itemsChanged": 0,
            },
            headers=library_headers(library.version),
        )

    version = await writes.bump_library_version(session, library)
    changed = await objectwrites.rename_tag(session, library, tag_name, new_name, version)
    renamed = await tags_service.get_tag(session, library, new_name)
    await session.commit()

    return JSONResponse(
        {
            "tag": renamed.name,
            "type": renamed.type,
            "numItems": renamed.num_items,
            # What the confirmation says, and the one number the reader cannot
            # work out from the panel: a merge leaves fewer items than either
            # tag's own count would suggest.
            "itemsChanged": len(changed),
        },
        headers=library_headers(version),
    )
