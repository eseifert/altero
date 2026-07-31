"""ASGI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from altero import API_VERSION, __version__
from altero.api.errors import register_error_handlers
from altero.api.routes import itemschema, keys
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
    app.include_router(itemschema.router)
    app.include_router(keys.router)

    @app.middleware("http")
    async def add_api_version_header(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Zotero-API-Version"] = str(API_VERSION)
        return response

    return app
