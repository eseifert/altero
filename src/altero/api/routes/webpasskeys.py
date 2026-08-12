"""Passkeys, over HTTP.

Two of these answer with no session and no CSRF token, and they are the
sign-in pair. A passkey sign-in starts with nobody claiming to be anybody: the
browser is asked what it holds for this site, and the assertion that comes back
says whose it is. That is why no username is taken, and it is what makes
account enumeration impossible here -- there is no form that behaves
differently for a name that exists.

**No CSRF token, for the same reason ``/web/auth/login`` takes none.** The
token lives in a cookie this server sets when somebody signs in, so a browser
that has never signed in does not have one -- which is precisely the browser
this pair exists for. Requiring it would make passkey sign-in impossible for a
first-time visitor while protecting nothing: completing either route grants
exactly what signing in grants, and a page on another origin cannot obtain an
assertion at all, because WebAuthn binds one to the relying party id and the
browser will not produce it for anybody else.

The account's own routes below *do* take it. Those change a signed-in account,
so the token is both available and load-bearing.
"""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import (
    AuthenticatedDep,
    CsrfDep,
    CurrentUserDep,
    PendingSessionDep,
    _serialise,
    _set_session_cookies,
)
from altero.errors import ForbiddenError
from altero.models import PasskeyCredential
from altero.services import account, passkeys, websessions

router = APIRouter(prefix="/web", tags=["web"])


class Ceremony(BaseModel):
    """What the browser produced. Shape is the library's business, not ours."""

    credential: dict
    name: str = ""


class Rename(BaseModel):
    name: str


class PasswordOnly(BaseModel):
    current_password: str | None = Field(default=None, alias="currentPassword")


def _party(request: Request) -> passkeys.RelyingParty:
    """Return this deployment's relying party, or say what is missing.

    A passkey is bound to this at enrolment, so it comes from ``public_url``
    and is never guessed from the request -- see services/passkeys.py.
    """
    return passkeys.relying_party(request.app.state.settings.public_url)


def _serialise_passkey(record: PasskeyCredential) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "created": record.created.isoformat() + "Z",
        "lastUsed": record.last_used.isoformat() + "Z" if record.last_used else None,
        # Whether this one lives on a single device, which is worth telling
        # somebody whose only passkey it is.
        "backedUp": record.backed_up,
        "transports": [entry for entry in record.transports.split(",") if entry],
    }


# --------------------------------------------------------------------------
# Signing in
# --------------------------------------------------------------------------


@router.post("/auth/passkey/options")
async def sign_in_options(request: Request, session: SessionDep) -> Response:
    """Ask the browser for whatever passkey it holds for this site.

    No session, no username and no CSRF token -- see this module's docstring.
    Every caller gets the same answer, so this cannot be used to ask whether an
    account exists.
    """
    return JSONResponse(await passkeys.begin_authentication(session, party=_party(request)))


@router.post("/auth/passkey/verify")
async def sign_in(
    request: Request,
    session: SessionDep,
    body: Annotated[Ceremony, Body()],
) -> Response:
    """Open a session from a passkey assertion.

    ``needsFactor`` is null: the authenticator has already established presence
    and, with user verification required, identity. Asking for a code from an
    authenticator app afterwards would add something weaker than what was just
    presented -- see services/passkeys.py.
    """
    try:
        user, _ = await passkeys.finish_authentication(
            session, body.credential, party=_party(request)
        )
    except ForbiddenError as error:
        raise HTTPException(status_code=401, detail=error.message) from error

    token, record = await websessions.create(
        session, user, user_agent=request.headers.get("user-agent", "")
    )
    # The passkey is proof enough to change things straight away, which is not
    # true of a password alone -- it is the stronger credential of the two.
    await account.stamp_proof(session, record)

    response = JSONResponse(
        {"user": _serialise(user), "needsFactor": None, "alternativeFactors": []}
    )
    _set_session_cookies(response, request, token)
    return response


@router.post("/auth/passkey/factor")
async def satisfy_factor(
    request: Request,
    session: SessionDep,
    record: PendingSessionDep,
    body: Annotated[Ceremony, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Clear an outstanding second factor with a passkey.

    For the account that signed in with a password and would rather touch a key
    than read a code. The passkey has to be one of *this* account's, which is
    what the challenge's own ``user_id`` pins down.
    """
    if record.pending_factor is None:
        raise HTTPException(status_code=401, detail="This session is not waiting for a factor")

    try:
        user, _ = await passkeys.finish_authentication(
            session, body.credential, party=_party(request), purpose="reauth"
        )
    except ForbiddenError as error:
        raise HTTPException(status_code=401, detail=error.message) from error

    if user.id != record.user_id:
        raise HTTPException(status_code=401, detail="That passkey belongs to a different account")

    record.pending_factor = None
    await account.stamp_proof(session, record)
    return JSONResponse({"user": _serialise(user), "needsFactor": None})


# --------------------------------------------------------------------------
# An account's own passkeys
# --------------------------------------------------------------------------


@router.get("/account/passkeys")
async def list_passkeys(session: SessionDep, user: CurrentUserDep) -> Response:
    return JSONResponse(
        {
            "passkeys": [
                _serialise_passkey(entry) for entry in await passkeys.credentials_for(session, user)
            ]
        }
    )


@router.post("/account/passkeys/options", status_code=201)
async def enrolment_options(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    record: AuthenticatedDep,
    body: Annotated[PasswordOnly, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Start enrolling a passkey.

    Takes proof, because a passkey is a way *in* rather than a second step in
    front of one -- the same rule as making an API key, and unlike enrolling an
    authenticator app, which only ever adds a hurdle.

    Asked for here rather than at the second step, so an authenticator is not
    touched before the browser knows the answer will be accepted.
    """
    await account.require_proof(session, user, record, password=body.current_password)
    return JSONResponse(
        await passkeys.begin_registration(session, user, party=_party(request)), status_code=201
    )


@router.post("/account/passkeys", status_code=201)
async def enrol(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    record: AuthenticatedDep,
    body: Annotated[Ceremony, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Store the passkey the authenticator just made."""
    stored = await passkeys.finish_registration(
        session, user, body.credential, party=_party(request), name=body.name
    )
    return JSONResponse({"passkey": _serialise_passkey(stored)}, status_code=201)


@router.patch("/account/passkeys/{passkey_id}")
async def rename_passkey(
    session: SessionDep,
    user: CurrentUserDep,
    passkey_id: int,
    body: Annotated[Rename, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Rename one. No proof: a label is not a credential."""
    stored = await session.get(PasskeyCredential, passkey_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No such passkey")

    await passkeys.rename(session, user, stored, body.name)
    return JSONResponse({"passkey": _serialise_passkey(stored)})


@router.delete("/account/passkeys/{passkey_id}", status_code=204)
async def remove_passkey(
    session: SessionDep,
    user: CurrentUserDep,
    record: AuthenticatedDep,
    passkey_id: int,
    body: Annotated[PasswordOnly, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Remove one, refusing to leave an account with no way in at all."""
    await account.require_proof(session, user, record, password=body.current_password)

    stored = await session.get(PasskeyCredential, passkey_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No such passkey")

    await passkeys.remove(session, user, stored)
    return Response(status_code=204)
