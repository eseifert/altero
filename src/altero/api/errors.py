"""Translation of domain errors into HTTP responses.

The Zotero API answers with a plain-text reason rather than a JSON body, so all
handlers here render ``text/plain``.
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from altero.errors import AlteroError, ForbiddenError, InvalidInputError, NotFoundError

#: Status code used for each domain error. Subclasses fall back to 500.
STATUS_CODES: dict[type[AlteroError], int] = {
    InvalidInputError: 400,
    ForbiddenError: 403,
    NotFoundError: 404,
}


async def handle_domain_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, AlteroError)
    status_code = next(
        (code for type_, code in STATUS_CODES.items() if isinstance(exc, type_)),
        500,
    )
    return PlainTextResponse(exc.message, status_code=status_code)


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
