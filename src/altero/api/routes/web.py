"""Endpoints for the web interface.

Everything here is under ``/web`` and authenticates with a cookie. Nothing here
is reachable with an API key, and nothing outside here is reachable with a
cookie -- see ``TestTheV3ApiIsUntouched`` in ``tests/test_web_routes.py``. Two
credentials for one endpoint would mean the browser attaching one of them to
whatever request a third party could provoke, with the whole sync protocol
behind it.

Cross-site request forgery is handled by double submission: a readable cookie
holding a random token, which the client echoes in a header. A page on another
origin can cause the browser to send the cookie but cannot read it, so it
cannot produce the header. ``SameSite=Lax`` already stops the simple version of
that attack; the token is what remains when the attacker is on a sibling
subdomain, where SameSite does not help.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import API_VERSION, __version__
from altero.api.deps import SessionDep
from altero.errors import ForbiddenError
from altero.models import User, WebSession
from altero.services import webauth, websessions

router = APIRouter(prefix="/web", tags=["web"])

#: Holds the session token. Not readable by script: it is the credential.
SESSION_COOKIE = "altero_session"

#: Holds the CSRF token. Readable by script on purpose -- the client has to be
#: able to copy it into a header.
CSRF_COOKIE = "altero_csrf"

CSRF_HEADER = "X-CSRF-Token"


class Credentials(BaseModel):
    username: str
    password: str


class Registration(Credentials):
    display_name: str = Field(default="", alias="displayName")


class Code(BaseModel):
    code: str


def _serialise(user: User) -> dict:
    """Return the user as the browser client consumes it."""
    return {"id": user.id, "username": user.username, "displayName": user.display_name}


def _is_secure(request: Request) -> bool:
    """Return whether cookies may carry the ``Secure`` flag.

    Set from the scheme the request actually arrived on, because marking a
    cookie Secure over plain HTTP means the browser discards it and nobody can
    sign in at all -- which is the state a developer on localhost would hit.
    """
    return request.url.scheme == "https"


def _set_session_cookies(response: Response, request: Request, token: str) -> None:
    """Attach the session and CSRF cookies to ``response``."""
    secure = _is_secure(request)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=websessions.LIFETIME_DAYS * 24 * 60 * 60,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=websessions.LIFETIME_DAYS * 24 * 60 * 60,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    """Drop the credential, keep the CSRF token.

    The token is a random per-browser value that authenticates nothing; what it
    does is let the client prove a request came from a page that could read it.
    Clearing it would leave the browser unable to produce a matching pair, so
    the next unsafe request -- including signing out again after the session
    had already gone -- would be refused rather than answered.
    """
    response.delete_cookie(SESSION_COOKIE, path="/")


async def get_current_session(request: Request, session: SessionDep) -> WebSession:
    """Return the session the cookie identifies, whatever state it is in."""
    record = await websessions.lookup(session, request.cookies.get(SESSION_COOKIE))
    if record is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return record


PendingSessionDep = Annotated[WebSession, Depends(get_current_session)]


async def get_authenticated_session(record: PendingSessionDep) -> WebSession:
    """Return the session, requiring that every factor has been cleared."""
    if not websessions.is_authenticated(record):
        raise HTTPException(status_code=401, detail="A second factor is still required")
    return record


AuthenticatedDep = Annotated[WebSession, Depends(get_authenticated_session)]


async def get_current_user(record: AuthenticatedDep, session: SessionDep) -> User:
    user = await session.get(User, record.user_id)
    if user is None:  # pragma: no cover - a session outlives its user only if deleted
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_csrf(request: Request) -> None:
    """Refuse an unsafe request whose header does not match its cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")


CsrfDep = Annotated[None, Depends(require_csrf)]


@router.get("/config")
async def read_config(session: SessionDep) -> Response:
    """Public facts the sign-in page needs before anyone has signed in.

    Whether registration is open decides if the page offers a register link at
    all; getting this wrong either hides the only way in to a fresh instance or
    advertises one that will be refused.
    """
    return JSONResponse(
        {
            "version": __version__,
            "apiVersion": API_VERSION,
            "registrationOpen": await webauth.registration_open(session),
            "secondFactors": ["totp"],
        }
    )


@router.post("/auth/register", status_code=201)
async def register(session: SessionDep, request: Request, body: Registration) -> Response:
    """Create the first account, or another if registration has been opened."""
    user = await webauth.register(
        session,
        username=body.username,
        password=body.password,
        display_name=body.display_name,
    )
    token, _ = await websessions.create(
        session, user, user_agent=request.headers.get("user-agent", "")
    )
    response = JSONResponse({"user": _serialise(user), "needsFactor": None}, status_code=201)
    _set_session_cookies(response, request, token)
    return response


@router.post("/auth/login")
async def login(session: SessionDep, request: Request, body: Credentials) -> Response:
    """Check a password and open a session, which may still want a factor."""
    try:
        result = await webauth.login(
            session,
            username=body.username,
            password=body.password,
            user_agent=request.headers.get("user-agent", ""),
        )
    except ForbiddenError as error:
        # 401 rather than the 403 the domain error maps to: the credential was
        # wrong, not insufficient, and the browser client tells those apart.
        raise HTTPException(status_code=401, detail=error.message) from error

    user = await session.get(User, result.session.user_id)
    assert user is not None
    payload = {
        "user": _serialise(user) if result.needs_factor is None else None,
        "needsFactor": result.needs_factor,
    }
    response = JSONResponse(payload)
    _set_session_cookies(response, request, result.token)
    return response


@router.post("/auth/totp")
async def submit_totp(
    session: SessionDep,
    record: PendingSessionDep,
    body: Annotated[Code, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Clear an outstanding TOTP factor on the current session."""
    try:
        await webauth.complete_totp(session, record, body.code)
    except ForbiddenError as error:
        raise HTTPException(status_code=401, detail=error.message) from error

    user = await session.get(User, record.user_id)
    assert user is not None
    return JSONResponse({"user": _serialise(user), "needsFactor": None})


@router.get("/auth/session")
async def read_session(user: CurrentUserDep) -> Response:
    """Report who the cookie signs in, for the client to restore its state."""
    return JSONResponse({"user": _serialise(user)})


@router.post("/auth/logout", status_code=204)
async def logout(session: SessionDep, request: Request, _csrf: CsrfDep) -> Response:
    """End the current session.

    Answers 204 whether or not there was one to end, so that a client whose
    session already expired is not made to handle a failure on its way out.
    """
    record = await websessions.lookup(session, request.cookies.get(SESSION_COOKIE))
    if record is not None:
        await websessions.revoke(session, record)

    response = Response(status_code=204)
    _clear_session_cookies(response)
    return response
