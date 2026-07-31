"""ASGI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from altero import API_VERSION, __version__
from altero.api.errors import register_error_handlers
from altero.api.routes import (
    collections,
    deleted,
    files,
    fulltext,
    items,
    itemschema,
    keys,
    searches,
    tags,
)
from altero.api.routes import (
    settings as settings_routes,
)
from altero.db import Database
from altero.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Zotero Web API application."""
    settings = get_settings() if settings is None else settings
    database = Database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title="altero",
        version=__version__,
        summary=f"Zotero Web API v{API_VERSION}",
        lifespan=lifespan,
        debug=settings.debug,
    )
    app.state.settings = settings
    app.state.database = database

    # A browser can only read a response header that is named here, and the
    # API's whole protocol lives in headers: without this a web client cannot
    # see Last-Modified-Version and so cannot sync at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["HEAD", "GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "If-Match",
            "If-None-Match",
            "If-Modified-Since-Version",
            "If-Unmodified-Since-Version",
            "Zotero-API-Key",
            "Zotero-API-Version",
            "Zotero-Schema-Version",
            "Zotero-Write-Token",
        ],
        expose_headers=[
            "Backoff",
            "ETag",
            "Last-Modified-Version",
            "Link",
            "Retry-After",
            "Total-Results",
            "Zotero-API-Version",
        ],
        max_age=86400,
    )

    register_error_handlers(app)
    # The schema routes come first so that /items/new is not captured by the
    # library-scoped /items/{item_key} pattern.
    app.include_router(itemschema.router)
    app.include_router(keys.router)
    app.include_router(deleted.router)
    app.include_router(settings_routes.router)
    app.include_router(fulltext.router)
    app.include_router(files.router)
    app.include_router(tags.router)
    app.include_router(collections.router)
    app.include_router(searches.router)
    app.include_router(items.router)

    @app.middleware("http")
    async def negotiate_api_version(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        """Answer only for the API version this server implements.

        A client asking for v1 or v2 would expect Atom, which is not served
        here, so saying so is better than returning v3 bodies under a v2 label.
        """
        header = request.headers.get("Zotero-API-Version")
        parameter = request.query_params.get("v")

        if header and parameter and header != parameter:
            return PlainTextResponse(
                "Zotero-API-Version header does not match 'v' query parameter",
                status_code=400,
            )

        requested = header or parameter
        if requested and requested != str(API_VERSION):
            return PlainTextResponse(
                f"Invalid API version '{requested}'; this server implements {API_VERSION}",
                status_code=400,
            )

        response = await call_next(request)
        response.headers["Zotero-API-Version"] = str(API_VERSION)
        return response

    return app
