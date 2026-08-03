"""ASGI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from altero import API_VERSION, __version__
from altero.api.compression import DecompressionMiddleware
from altero.api.errors import register_error_handlers
from altero.api.ratelimit import RateLimitMiddleware
from altero.api.routes import (
    collections,
    deleted,
    files,
    fulltext,
    health,
    items,
    itemschema,
    keys,
    publications,
    searches,
    tags,
    web,
    weblibrary,
)
from altero.api.routes import (
    settings as settings_routes,
)
from altero.api.spa import mount_web_interface
from altero.db import Database
from altero.services.mail import build_mailer
from altero.services.ratelimit import RateLimiter
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
        # Never on: the client logs the whole response body, so a traceback
        # would end up in the user's debug output and in bug reports.
        debug=False,
    )
    app.state.settings = settings
    app.state.database = database
    # Built once, at start-up, so a malformed smtp URL is a start-up
    # failure rather than a surprise the first time someone registers.
    app.state.mailer = build_mailer(settings)

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

    # Outermost, so the body is already decompressed by the time anything else
    # looks at it.
    app.add_middleware(DecompressionMiddleware)

    # Refuse before doing any work, including before decompressing a body.
    limiter = RateLimiter(limit=settings.rate_limit, window=settings.rate_limit_window)
    app.state.rate_limiter = limiter
    app.middleware("http")(RateLimitMiddleware(app, limiter))

    register_error_handlers(app)
    # The schema routes come first so that /items/new is not captured by the
    # library-scoped /items/{item_key} pattern.
    # The web interface's own namespace, before the library-scoped routes.
    app.include_router(web.router)
    app.include_router(weblibrary.router)
    app.include_router(health.router)
    app.include_router(itemschema.router)
    app.include_router(keys.router)
    app.include_router(deleted.router)
    app.include_router(settings_routes.router)
    app.include_router(fulltext.router)
    app.include_router(files.router)
    app.include_router(tags.router)
    app.include_router(collections.router)
    app.include_router(publications.router)
    app.include_router(searches.router)
    app.include_router(items.router)

    # Last, so every API route is already registered and nothing under
    # /app can capture one of them.
    mount_web_interface(app)

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
