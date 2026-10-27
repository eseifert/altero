"""A library's versions, pushed to a page that has it open.

The browser's counterpart to the streaming API, and deliberately not that
API: ``/stream`` takes an API key, and a cookie must never reach the v3
surface. This is a Server-Sent Events feed under ``/web``, behind the browser
session, carrying the same one fact the streaming API carries -- a library's
new version -- for one library, so that a page can read again what it shows.
No object travels here; reading the change is the page's ordinary request,
which is where permissions are applied.

Fed by the in-memory broker, so it works in one process and no further, as
the streaming API does.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from altero.api.deps import SessionDep
from altero.api.routes.web import SESSION_COOKIE, CurrentUserDep
from altero.models import Library
from altero.services import auth, websessions
from altero.services.streaming import AccessChanged, TopicUpdated, broker, topic_for

router = APIRouter(prefix="/web", tags=["web"])

#: How long a quiet feed waits before saying it is still there, and asking
#: again whether its reader may still listen: a session signed out or
#: suspended, or a membership ended, closes the feed by the next one.
HEARTBEAT_SECONDS = 25.0

#: How long the browser waits before reconnecting a feed that ended.
RETRY_MILLISECONDS = 5000


def _event(version: int, *, retry: bool = False) -> str:
    head = f"retry: {RETRY_MILLISECONDS}\n" if retry else ""
    return f"{head}event: version\ndata: {json.dumps({'version': version})}\n\n"


@router.get("/libraries/{library_id}/events")
async def library_events(
    request: Request, session: SessionDep, user: CurrentUserDep, library_id: int
) -> Response:
    """Stream ``library_id``'s version: once on connecting, and on every change.

    The first event is the version the library has, so a page reconnecting
    after a dropped connection learns whether it missed anything.
    """
    library = await session.get(Library, library_id)
    if library is None:
        raise HTTPException(status_code=404, detail="No such library")
    if not (await auth.user_access(session, library, user.id)).read:
        raise HTTPException(status_code=403, detail="You cannot read this library")

    factory: Callable[[], Any] = request.app.state.database.session_factory
    token = request.cookies.get(SESSION_COOKIE)
    user_id = user.id
    topic = topic_for(library)

    async def allowed() -> int | None:
        """The library's version, if this reader may still listen; else ``None``."""
        fresh: AsyncSession
        async with factory() as fresh:
            record = await websessions.lookup(fresh, token)
            if record is None or record.user_id != user_id:
                return None
            if not websessions.is_authenticated(record):
                return None
            current = await fresh.get(Library, library_id)
            if current is None or not (await auth.user_access(fresh, current, user_id)).read:
                return None
            return current.version

    async def events() -> AsyncIterator[str]:
        # Attached before the first version is read, so that a write landing
        # in between is announced rather than missed.
        with broker.attach() as queue:
            version = await allowed()
            if version is None:
                return
            yield _event(version, retry=True)
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    if await allowed() is None:
                        return
                    yield ": still here\n\n"
                    continue
                if isinstance(message, TopicUpdated) and message.topic == topic:
                    yield _event(message.version)
                elif (
                    isinstance(message, AccessChanged)
                    and message.user_id == user_id
                    and await allowed() is None
                ):
                    return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Never kept, and never held back by a buffering proxy: an event that
        # arrives a minute late is a page that is a minute wrong.
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
