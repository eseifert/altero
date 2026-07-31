"""Translation of domain errors into HTTP responses.

The Zotero API answers with a plain-text reason rather than a JSON body, so all
handlers here render ``text/plain``.
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from altero.errors import (
    AlteroError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    RequestTooLargeError,
)

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


async def handle_domain_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, AlteroError)
    return PlainTextResponse(exc.message, status_code=status_for(exc))


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code, headers=exc.headers)


async def handle_validation_error(request: Request, exc: Exception) -> Response:
    """Report malformed parameters as 400, which is what the API documents."""
    assert isinstance(exc, RequestValidationError)
    invalid = ", ".join(str(error["loc"][-1]) for error in exc.errors())
    return PlainTextResponse(f"Invalid parameter: {invalid}", status_code=400)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AlteroError, handle_domain_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
