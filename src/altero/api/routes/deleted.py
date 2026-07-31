"""The delete log."""

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import Response

from altero.api.deps import ReadableLibraryDep, SessionDep
from altero.api.responses import object_response
from altero.errors import InvalidInputError
from altero.services import deletions

router = APIRouter(tags=["deleted"])


@router.get("/users/{user_id}/deleted")
@router.get("/groups/{group_id}/deleted")
async def list_deleted(
    request: Request,
    session: SessionDep,
    library: ReadableLibraryDep,
) -> Response:
    """Return everything removed from the library since a given version.

    A client that has been away syncs by asking what changed since the version
    it last saw; without this it could not tell a deletion from an object it
    simply had not fetched.
    """
    raw = request.query_params.get("since")
    if raw is None:
        raise InvalidInputError("'since' parameter not provided")
    try:
        since = int(raw)
    except ValueError:
        raise InvalidInputError(f"Invalid 'since' value '{raw}'") from None

    grouped = await deletions.list_deletions(session, library, since)
    return object_response(grouped, library.version)
