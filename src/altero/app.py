"""ASGI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

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
    groups,
    health,
    items,
    itemschema,
    keys,
    oauth,
    publications,
    searches,
    streaming,
    tags,
    web,
    webaccount,
    webadmin,
    webcollections,
    webgroups,
    webidentity,
    webitems,
    weblibrary,
    weblink,
    webmigrate,
    weboauth,
    webpasskeys,
    webprofile,
    webshares,
    webtags,
    webtransfer,
)
from altero.api.routes import (
    settings as settings_routes,
)
from altero.api.spa import mount_web_interface
from altero.db import Database
from altero.services import (
    groupdigest,
    instancesettings,
    passkeys,
    passwordreset,
    retention,
)
from altero.services.groupsweeper import Sweeper
from altero.services.mail import build_mailer
from altero.services.ratelimit import RateLimiter
from altero.settings import Settings, get_settings

logger = logging.getLogger("altero.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Zotero Web API application."""
    settings = get_settings() if settings is None else settings
    database = Database(settings)

    async def sweep_digests() -> int:
        """Deliver whatever group activity has settled since the last look."""
        async with database.session_factory() as session:
            return await groupdigest.sweep(
                session,
                app.state.mailer.send,
                quiet_period=timedelta(seconds=settings.group_digest_quiet_period),
            )

    async def sweep_retention() -> int:
        """Apply the operator's retention periods.

        Off unless `retention_interval` says otherwise, which is the default:
        an instance that started deleting somebody's trash because it was
        upgraded would be a surprise of the worst kind.
        """
        async with database.session_factory() as session:
            values = await instancesettings.read_all(session, settings)
            report = await retention.sweep(session, values)
            if report.anything:
                logger.info("Retention sweep deleted %s", retention.describe(report))
            return report.items_deleted

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            # Inside the dispose, so that leaving this block stops the sweepers
            # -- and waits for a sweep in flight -- while the database they are
            # working against is still there.
            async with (
                Sweeper(sweep_digests, interval=timedelta(seconds=settings.group_digest_interval)),
                Sweeper(sweep_retention, interval=timedelta(seconds=settings.retention_interval)),
            ):
                yield
        finally:
            # The outbound client federated sign-in builds lazily, if anything
            # ever used it. Closed here so its connections do not outlive the
            # application in a test that makes several.
            client = getattr(app.state, "http_client", None)
            if client is not None:
                await client.aclose()
                app.state.http_client = None
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
    # Its own limiter rather than the API's: the API's is off by default and is
    # about a runaway sync client, while this one is about a form anybody on
    # the internet can submit and must hold whatever the deployment configured.
    # Per process, like the other one, and for the same reason -- see
    # services/ratelimit.py.
    app.state.reset_limiter = RateLimiter(
        limit=passwordreset.REQUESTS_PER_WINDOW,
        window=passwordreset.REQUEST_WINDOW_SECONDS,
    )
    # Checked at start-up rather than at the first enrolment, because a passkey
    # is bound to this and a wrong one is not a failure anybody sees: every
    # passkey simply stops working, weeks later, with nothing to connect it to
    # a configuration change. A deployment with no public URL is left without
    # passkeys rather than refused -- most instances have neither.
    if settings.public_url:
        party = passkeys.relying_party(settings.public_url)
        logger.info("Passkeys are bound to %s", party.id)

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
    app.include_router(webcollections.router)
    app.include_router(webitems.router)
    app.include_router(webtags.router)
    app.include_router(webmigrate.router)
    app.include_router(webaccount.router)
    app.include_router(webadmin.router)
    app.include_router(webidentity.router)
    app.include_router(webpasskeys.router)
    app.include_router(webgroups.router)
    app.include_router(webtransfer.router)
    app.include_router(webprofile.router)
    app.include_router(webshares.router)
    app.include_router(weboauth.router)
    app.include_router(weblink.router)
    app.include_router(health.router)
    app.include_router(oauth.router)
    app.include_router(streaming.router)
    app.include_router(itemschema.router)
    app.include_router(keys.router)
    app.include_router(groups.router)
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
