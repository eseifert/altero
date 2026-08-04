"""Serving the built web interface.

Mounted under ``/app`` and nowhere else. The v3 API owns the root namespace --
``/users``, ``/groups``, ``/items``, ``/keys`` and the rest -- so a catch-all at
``/`` would shadow it, and a client asking for an item it is entitled to would
be handed an HTML page instead.

Within ``/app`` the router is the browser's, so any path that is not a built
file has to return ``index.html`` and let the application work out what it
means. Without that, reloading the page on /app/sign-in is a 404.
"""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.staticfiles import StaticFiles

#: Where `npm run build` puts its output, inside the installed package.
STATIC_ROOT = Path(__file__).resolve().parent.parent / "web" / "static"

#: Path prefix the interface is served under.
MOUNT_PATH = "/app"


def is_built(root: Path | None = None) -> bool:
    """Return whether there is a built interface to serve."""
    return ((root or STATIC_ROOT) / "index.html").is_file()


#: How long a fingerprinted asset may be kept. Its name changes when its
#: contents do, so there is nothing to come back and check for.
ASSET_CACHE = "public, max-age=31536000, immutable"


class SinglePageApp(StaticFiles):
    """Static files, falling back to ``index.html`` for unknown paths.

    Only for paths the browser could have routed to. A missing asset stays a
    404: answering with HTML would make a mistyped script URL look like a
    working page that silently does nothing.
    """

    async def get_response(self, path: str, scope) -> Response:  # type: ignore[no-untyped-def]
        try:
            response = await super().get_response(path, scope)
        except HTTPException as missing:
            # StaticFiles raises rather than returning the 404, so this has to
            # be caught: checking the returned status never fires.
            if missing.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)

        # Everything under assets/ carries a hash of its contents in its name,
        # so it can be kept for good. Reading a Japanese library pulls some
        # thirty font subsets; without this each one is asked about again on
        # every page load, only to be told it has not changed. index.html is
        # deliberately not in here: it is what names the current assets.
        if path.startswith("assets/") and response.status_code == 200:
            response.headers["cache-control"] = ASSET_CACHE
        return response


def mount_web_interface(app: FastAPI, root: Path | None = None) -> bool:
    """Serve the built interface under ``/app``, if it has been built.

    Returns whether anything was mounted. A source checkout that has not run
    the frontend build is a normal state -- the API is entirely usable without
    it -- so this says so rather than failing to start.
    """
    static_root = root or STATIC_ROOT

    if not is_built(static_root):

        @app.get(MOUNT_PATH, include_in_schema=False)
        @app.get(f"{MOUNT_PATH}/{{path:path}}", include_in_schema=False)
        async def _unbuilt(request: Request, path: str = "") -> Response:
            return PlainTextResponse(
                "The web interface has not been built. Run `npm install && npm run build` "
                "in web/, or use an image built by docker/Dockerfile.",
                status_code=503,
            )

        return False

    @app.get("/", include_in_schema=False)
    async def _root() -> Response:
        """Send a browser at the root to the interface.

        A redirect rather than serving the page here, so that the root keeps
        belonging to the API and only this one method is spent on it.
        """
        return FileResponse(static_root / "index.html")

    app.mount(MOUNT_PATH, SinglePageApp(directory=static_root, html=True), name="web")
    return True
