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
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import API_VERSION, __version__
from altero.api.deps import SessionDep
from altero.errors import ForbiddenError
from altero.models import User, WebSession
from altero.services import emailverify, passwordreset, passwords, webauth, websessions
from altero.services.mail import Message
from altero.services.passwordreset import LIFETIME_HOURS

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
    email: str
    display_name: str = Field(default="", alias="displayName")


class Code(BaseModel):
    code: str


class Token(BaseModel):
    token: str


def _serialise(user: User) -> dict:
    """Return the user as the browser client consumes it."""
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "email": user.email,
        "emailVerified": user.email_verified is not None,
        # Null means "follow the browser" rather than "unset", so it is sent as
        # null rather than filled in with a default the account did not choose.
        "language": user.language,
        "timeZone": user.time_zone,
        # Who may read this account's profile page. Reported to the account
        # itself and to nobody else -- see altero/api/routes/webprofile.py.
        "profileVisibility": user.profile_visibility.value,
        # Whether this account administers the instance. The interface shows
        # the administration screens from this alone; every route behind them
        # checks it again for itself.
        "administrator": user.administrator,
    }


def reset_link(request: Request, token: str) -> str:
    """Return the absolute URL a password-reset link points at.

    Built the same way as the confirmation link below, and public because it is
    the administration screens that issue one -- see
    `api/routes/webadmin.py`.
    """
    configured = request.app.state.settings.public_url.rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    return f"{base}/app/reset?token={quote(token)}"


def _verification_link(request: Request, token: str) -> str:
    """Return the absolute URL the confirmation mail points at.

    Prefers the configured public URL, because the address a request arrived on
    is the proxy's idea of it and behind one that rewrites the host the link
    would point somewhere nobody can reach.
    """
    configured = request.app.state.settings.public_url.rstrip("/")
    base = configured or str(request.base_url).rstrip("/")
    return f"{base}/app/verify?token={quote(token)}"


async def _send_verification(
    request: Request, session: AsyncSession, user: User, address: str | None = None
) -> None:
    """Issue a confirmation for ``address`` and try to deliver it.

    Failure to send is deliberately not failure to register. With no relay
    configured the link is written to the log instead, which is how the owner
    of a fresh container finishes signing up.
    """
    email = address or user.email or ""
    token = await emailverify.issue(session, user, email)
    link = _verification_link(request, token)
    await request.app.state.mailer.send(
        Message(
            to=email,
            subject="Confirm your email address for altero",
            body=(
                f"Hello {user.display_name or user.username},\n\n"
                "Confirm this address to receive security notifications and "
                "invitations from this altero server:\n\n"
                f"    {link}\n\n"
                f"The link is good for {emailverify.LIFETIME_HOURS} hours. "
                "Your account already works without it.\n"
            ),
        )
    )


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


async def get_viewer(request: Request, session: SessionDep) -> User | None:
    """Return who is signed in, or ``None``, without refusing anybody.

    For the pages that are readable by strangers -- a profile and the
    publications on it -- where being signed in changes what may be seen but
    not whether the request is answered. Everything else takes
    :data:`CurrentUserDep`, which refuses.

    A session part-way through a second factor counts as nobody: it holds a
    real cookie and has not finished proving whose it is.
    """
    record = await websessions.lookup(session, request.cookies.get(SESSION_COOKIE))
    if record is None or not websessions.is_authenticated(record):
        return None
    return await session.get(User, record.user_id)


ViewerDep = Annotated[User | None, Depends(get_viewer)]


def require_csrf(request: Request) -> None:
    """Refuse an unsafe request whose header does not match its cookie."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")


CsrfDep = Annotated[None, Depends(require_csrf)]


@router.get("/config")
async def read_config(request: Request, session: SessionDep) -> Response:
    """Public facts the sign-in page needs before anyone has signed in.

    Whether registration is open decides if the page offers a register link at
    all; getting this wrong either hides the only way in to a fresh instance or
    advertises one that will be refused. It reports the general case: somebody
    holding an invitation may register on an instance that answers ``false``
    here, and reaches the form through the link in it rather than through this.
    """
    return JSONResponse(
        {
            "version": __version__,
            "apiVersion": API_VERSION,
            "registrationOpen": await webauth.registration_open(
                session, allow=request.app.state.settings.open_registration
            ),
            # Whether the form the visitor is about to see is the one that
            # claims the instance. The two are different sentences, and the
            # page cannot tell them apart from `registrationOpen` alone.
            "firstAccount": await webauth.no_accounts_yet(session),
            "secondFactors": ["totp"],
            # Whether the sign-in page offers "forgotten your password?" at
            # all. Reported rather than assumed, so an instance that has no
            # relay does not show a form that can only ever answer 202 and
            # send nothing.
            "passwordResetOpen": _reset_allowed(request),
        }
    )


@router.post("/auth/register", status_code=201)
async def register(session: SessionDep, request: Request, body: Registration) -> Response:
    """Create the first account, or another if registration has been opened."""
    user = await webauth.register(
        session,
        username=body.username,
        password=body.password,
        email=body.email,
        display_name=body.display_name,
        allow_registration=request.app.state.settings.open_registration,
    )
    await _send_verification(request, session, user)
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


class AddressChange(BaseModel):
    email: str


@router.post("/auth/verify")
async def verify_email(session: SessionDep, body: Annotated[Token, Body()]) -> Response:
    """Confirm an address from the token in a link.

    Deliberately needs no session and no CSRF token: the link is followed in
    whatever browser happens to be open, frequently not the one that
    registered, and the token in it is the whole credential.
    """
    user = await emailverify.confirm(session, body.token)
    return JSONResponse({"user": _serialise(user)})


class NewPassword(Token):
    password: str


class ForgottenPassword(BaseModel):
    email: str


def _reset_allowed(request: Request) -> bool:
    """Return whether this deployment offers a self-service reset at all.

    Both halves are required and neither is a substitute for the other: the
    operator has to have asked for it, and there has to be somewhere for the
    link to go. Without a relay the message is written to the log, which is
    the right fallback for a confirmation somebody is waiting for and the
    wrong one entirely for a credential -- anybody who can read the log could
    then take any account on the instance.
    """
    settings = request.app.state.settings
    return bool(settings.password_reset and settings.smtp_url)


@router.post("/auth/forgot", status_code=202)
async def forgot_password(
    request: Request, session: SessionDep, body: Annotated[ForgottenPassword, Body()]
) -> Response:
    """Send a link to set a new password, if this address has an account.

    **202 whatever happens**, and deliberately so. A response that told a
    caller whether anything was sent would answer "does this person have an
    account here", one address at a time, to anybody who asked -- and the
    people most likely to ask are not the ones who forgot a password. The same
    silence covers a closed instance, an unknown address, an unconfirmed one,
    a suspended account and a relay that is down.

    No session and no CSRF token: whoever is looking at this form is by
    definition not signed in, and there is nothing to forge -- the request
    grants nothing and the link goes to the address on the account rather than
    anywhere the caller named.

    The rate limit is keyed by address rather than by the caller's own, because
    the thing worth bounding is how much mail one mailbox can be made to
    receive; a limit on the sender would be evaded by the same botnet that
    made it necessary.
    """
    if not _reset_allowed(request):
        return Response(status_code=202)

    limiter = request.app.state.reset_limiter
    if limiter.check(body.email.strip().lower()) is not None:
        return Response(status_code=202)

    issued = await passwordreset.self_service(session, body.email)
    if issued is None:
        return Response(status_code=202)

    user, token = issued
    assert user.email is not None
    await request.app.state.mailer.send(
        Message(
            to=user.email,
            subject="Set a new password for altero",
            body=(
                f"Hello {user.display_name or user.username},\n\n"
                "Somebody asked to set a new password for the altero account "
                f"'{user.username}'. If it was you, follow this link:\n\n"
                f"    {reset_link(request, token)}\n\n"
                f"The link is good for {LIFETIME_HOURS} hours and can be used "
                "once. Every browser signed in to the account will be signed "
                "out when it is used.\n\n"
                "If it was not you, there is nothing to do: your password has "
                "not changed and this link is the only thing that was made.\n"
            ),
        )
    )
    return Response(status_code=202)


@router.get("/auth/reset/{token}")
async def read_reset(session: SessionDep, token: str) -> Response:
    """Say whose password a link is about to set, before asking for one.

    Needs no session and no CSRF token, like the confirmation link: it is
    followed in whatever browser is open, and the token is the whole
    credential. What it discloses is the username the link was issued for,
    which whoever holds the link was told anyway.
    """
    user = await passwordreset.resolve(session, token)
    return JSONResponse({"username": user.username, "displayName": user.display_name})


@router.post("/auth/reset")
async def complete_reset(session: SessionDep, body: Annotated[NewPassword, Body()]) -> Response:
    """Set a password from a link an administrator issued.

    The token is checked first and spent only once the new password has been
    validated, so a password too short to be accepted does not cost somebody
    their only way in.

    Every other session of that account ends, and the owner is told, because
    this goes through the same `set_password` a change in settings does.
    """
    user = await passwordreset.resolve(session, body.token)
    passwords.validate_password(body.password)

    await passwordreset.consume(session, body.token)
    await webauth.set_password(session, user, body.password)
    return JSONResponse({"username": user.username})


@router.post("/auth/verify/resend", status_code=202)
async def resend_verification(
    request: Request, session: SessionDep, user: CurrentUserDep, _csrf: CsrfDep
) -> Response:
    """Send the confirmation again, to the address already on the account.

    202 whether or not anything was sent. Reporting delivery would tell a
    caller whether this address is already confirmed, and there is nothing the
    user can do about a relay that is down anyway.
    """
    if user.email and user.email_verified is None:
        await _send_verification(request, session, user)
    return Response(status_code=202)


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
