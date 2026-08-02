"""The readiness probe.

Unauthenticated on purpose: an orchestrator has no API key, and the check runs
before anyone has issued one. Nothing here reports anything a caller could not
learn by making an ordinary request.
"""

from fastapi import APIRouter
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.services import health

router = APIRouter(tags=["health"])


@router.get("/health")
async def read_health(session: SessionDep) -> Response:
    """Report whether this instance can actually serve."""
    try:
        return JSONResponse(await health.check(session))
    except SQLAlchemyError, OSError:
        # Deliberately says nothing else. The body is public, and a driver
        # error names the host, the path or the user it failed to connect as.
        return JSONResponse({"status": "error"}, status_code=503)
