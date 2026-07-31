"""ASGI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from altero import API_VERSION, __version__
from altero.api.errors import register_error_handlers
from altero.api.routes import (
    collections,
    deleted,
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

    register_error_handlers(app)
    # The schema routes come first so that /items/new is not captured by the
    # library-scoped /items/{item_key} pattern.
    app.include_router(itemschema.router)
    app.include_router(keys.router)
    app.include_router(deleted.router)
    app.include_router(settings_routes.router)
    app.include_router(fulltext.router)
    app.include_router(tags.router)
    app.include_router(collections.router)
    app.include_router(searches.router)
    app.include_router(items.router)

    @app.middleware("http")
    async def add_api_version_header(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Zotero-API-Version"] = str(API_VERSION)
        return response

    return app
