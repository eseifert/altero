"""Translation of domain errors into HTTP responses.

The Zotero API answers with a plain-text reason rather than a JSON body, so all
handlers here render ``text/plain``.
"""

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from altero.errors import (
    AlteroError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    OAuthError,
    PreconditionFailedError,
    PreconditionRequiredError,
    RequestTooLargeError,
)

#: Path prefix served for the web interface. Everything under it answers JSON;
#: everything outside it is the v3 API, which answers a plain-text reason and
#: whose response shape is not ours to change.
WEB_PREFIX = "/web"

#: Status code used for each domain error. Subclasses fall back to 500.
STATUS_CODES: dict[type[AlteroError], int] = {
    InvalidInputError: 400,
    ForbiddenError: 403,
    NotFoundError: 404,
    PreconditionFailedError: 412,
    RequestTooLargeError: 413,
    PreconditionRequiredError: 428,
}


def status_for(exc: AlteroError) -> int:
    """Return the status code that reports ``exc``.

    Also used for the per-object ``code`` of a multi-object write, where the
    failure is reported inside a 200 response rather than as the status.
    """
    return next(
        (code for type_, code in STATUS_CODES.items() if isinstance(exc, type_)),
        500,
    )


def _reply(
    request: Request, message: str, status_code: int, headers: Mapping[str, str] | None = None
) -> Response:
    """Render ``message`` the way the addressed API reports failure."""
    if request.url.path.startswith(WEB_PREFIX):
        return JSONResponse(
            {"message": message}, status_code=status_code, headers=dict(headers or {})
        )
    return PlainTextResponse(message, status_code=status_code, headers=dict(headers or {}))


async def handle_oauth_error(request: Request, exc: Exception) -> Response:
    """Report an OAuth failure the way RFC 6749 §5.2 says to.

    JSON with an ``error`` code whatever the path, because an OAuth client
    parses this and neither the v3 API's plain text nor the web interface's
    ``message`` is what it is looking for. ``invalid_client`` is the one that
    answers 401 rather than 400, and carries the challenge RFC 6749 asks for
    when the client tried to authenticate.
    """
    assert isinstance(exc, OAuthError)
    status = 401 if exc.code == "invalid_client" else 400
    headers = {"WWW-Authenticate": 'Basic realm="altero"'} if status == 401 else {}
    return JSONResponse(
        {"error": exc.code, "error_description": exc.message},
        status_code=status,
        headers=headers,
    )


async def handle_domain_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, AlteroError)
    return _reply(request, exc.message, status_for(exc))


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    return _reply(request, str(exc.detail), exc.status_code, exc.headers)


async def handle_validation_error(request: Request, exc: Exception) -> Response:
    """Report malformed parameters as 400, which is what the API documents."""
    assert isinstance(exc, RequestValidationError)
    invalid = ", ".join(str(error["loc"][-1]) for error in exc.errors())
    return PlainTextResponse(f"Invalid parameter: {invalid}", status_code=400)


def register_error_handlers(app: FastAPI) -> None:
    # Registered before the base class, since Starlette picks the most
    # specific handler by walking the exception's own class hierarchy.
    app.add_exception_handler(OAuthError, handle_oauth_error)
    app.add_exception_handler(AlteroError, handle_domain_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
