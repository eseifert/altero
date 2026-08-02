"""The shared shape of a multi-object write request."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.errors import status_for
from altero.api.responses import library_headers
from altero.errors import AlteroError
from altero.models import Library
from altero.services import writes

#: Saves one object and returns its serialized form, or ``None`` if the object
#: was already exactly what was sent.
Saver = Callable[[AsyncSession, Library, dict[str, Any], int], Awaitable[dict[str, Any] | None]]


async def batch_write(
    request: Request,
    session: AsyncSession,
    library: Library,
    save: Saver,
    *,
    require_version: bool = False,
) -> Response:
    """Apply a batch of objects and answer with the per-object report.

    Each object is applied inside a savepoint so that one rejection does not
    take the rest of the batch with it. A request in which nothing succeeded
    leaves the library version where it was.

    Args:
        require_version: Whether ``If-Unmodified-Since-Version`` must be
            supplied. The full-text upload requires it; the object writes accept
            a request without one.
    """
    payloads = writes.parse_object_list(await request.json())

    # Lock first, so the version this request checks is the one it goes on to
    # change.
    library = await writes.lock_library(session, library)
    expected = writes.parse_version_header(request.headers.get("If-Unmodified-Since-Version"))
    writes.check_library_version(library, expected, required=require_version)

    await writes.claim_write_token(session, library, request.headers.get("Zotero-Write-Token"))

    results = writes.WriteResults()
    # Held as a plain int: after a rollback the ORM object is expired, and
    # reading an attribute off it would trigger a lazy load with no session.
    previous_version = library.version
    version = await writes.bump_library_version(session, library)

    # Applied in the order sent, so an object may refer to one created earlier
    # in the same request.
    for index, payload in enumerate(payloads):
        key = str(payload.get("key") or "")
        savepoint = await session.begin_nested()
        try:
            rendered = await save(session, library, payload, version)
        except AlteroError as error:
            await savepoint.rollback()
            results.add_failure(index, key, status_for(error), error.message)
        else:
            if rendered is None:
                # Nothing differs, so nothing is written and the object keeps
                # the version it has. Rolling the savepoint back is what undoes
                # the version the save stamped on it on the way to finding out.
                await savepoint.rollback()
                results.add_unchanged(index, key)
            else:
                await savepoint.commit()
                results.add_successful(index, rendered)

    if results.any_succeeded:
        await session.commit()
    else:
        await session.rollback()
        version = previous_version

    return JSONResponse(results.report(), headers=library_headers(version))
