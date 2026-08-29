"""Approving an application, and taking the approval back.

The half of the authorization server that a person touches, and it is under
``/web`` with everything else a person touches: a cookie, a CSRF token on
anything that changes something, and no API key anywhere near it.

That placement is the design rather than a filing decision. Consent is a
decision by an account holder about their own library, so it belongs where
account holders are already authenticated -- which means the second factor, the
passkey and the single sign-on that :mod:`altero.services.webauth` already
enforces apply to it without a line of code here. An authorization server that
took a password of its own would be the weakest door in the building, and it
would be weakest precisely at the moment somebody is handing a stranger's
application the keys to their library.

Nothing here writes to a library. Approving an application creates a grant and
an authorization code; no object is touched and no library version moves, for
the same reason making a share does not -- see ``api/routes/webshares.py``.
"""

from typing import Annotated

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.api.spa import MOUNT_PATH
from altero.errors import InvalidInputError
from altero.services import oauthserver

router = APIRouter(prefix="/web/oauth", tags=["web"])


class DeviceCode(BaseModel):
    """A user code, as somebody typed it."""

    user_code: str = Field(alias="userCode")


class Decision(BaseModel):
    """Yes or no to one authorization request."""

    approve: bool


@router.get("/pending/{handle}")
async def read_pending(handle: str, session: SessionDep, user: CurrentUserDep) -> JSONResponse:
    """Describe what an application is asking for.

    Everything in the answer comes from the stored request, never from the
    query string that asked to see it. A consent screen whose text is supplied
    by the link that opened it describes whatever the link says it describes,
    which is the whole trick behind a convincing authorization phish.
    """
    pending = await oauthserver.pending(session, handle, user)
    return JSONResponse(
        {
            "handle": pending.handle,
            "clientId": pending.client_id,
            "name": pending.client_name,
            "description": pending.description,
            "scopes": pending.scopes,
            "newScopes": pending.new_scopes,
            "alreadyGranted": pending.already_granted,
        }
    )


@router.post("/pending/{handle}")
async def decide(
    handle: str,
    session: SessionDep,
    user: CurrentUserDep,
    _csrf: CsrfDep,
    decision: Annotated[Decision, Body()],
) -> JSONResponse:
    """Approve or refuse an authorization, answering with where to send the browser.

    The redirect is returned rather than performed, because the caller is the
    interface making a request from script and a 303 to another origin is not
    something it can follow usefully. Refusing redirects too: RFC 6749 §4.1.2.1
    asks that the application be told ``access_denied`` rather than left
    waiting, and an application that knows it was refused can say so instead of
    spinning.
    """
    redirect = (
        await oauthserver.approve(session, handle, user)
        if decision.approve
        else await oauthserver.deny(session, handle)
    )
    # A device authorization has no application address to return to, so what
    # comes back is empty and the browser is sent to the page that says the
    # device can be picked up again. Where the interface lives is this layer's
    # business rather than the service's.
    return JSONResponse({"redirect": redirect.url or f"{MOUNT_PATH}/device/done"})


@router.post("/device")
async def claim_device(
    session: SessionDep,
    _user: CurrentUserDep,
    _csrf: CsrfDep,
    body: Annotated[DeviceCode, Body()],
) -> JSONResponse:
    """Turn a code somebody typed into an authorization waiting for their answer.

    Answers with the handle of an ordinary pending authorization, which the
    interface then shows on the same consent screen every other application
    gets. That reuse is why this route is four lines: a device asks for scopes
    like anything else, and the only thing unusual about it is how the request
    got here.

    Under ``/web`` with a cookie and a CSRF token, because approving is a
    decision by an account holder -- so the second factor, the passkey and the
    single sign-on already guarding this door guard it here too.
    """
    handle = await oauthserver.claim_user_code(session, body.user_code)
    return JSONResponse({"handle": handle})


@router.get("/authorizations")
async def list_authorizations(session: SessionDep, user: CurrentUserDep) -> JSONResponse:
    """List every application this account has connected."""
    return JSONResponse(
        [
            {
                "id": entry.id,
                "clientId": entry.client_id,
                "name": entry.name,
                "description": entry.description,
                "scopes": entry.scopes,
                "approved": entry.approved.isoformat() + "Z",
                "activeTokens": entry.active_tokens,
            }
            for entry in await oauthserver.authorizations(session, user)
        ]
    )


@router.delete("/authorizations/{grant_id}", status_code=204)
async def withdraw_authorization(
    grant_id: int, session: SessionDep, user: CurrentUserDep, _csrf: CsrfDep
) -> Response:
    """Disconnect an application, taking its tokens with it.

    Immediate, not "when the access token expires". A person disconnecting an
    application has decided it should stop, and an hour of continued access
    while a token runs out is not what they were told would happen.
    """
    if grant_id < 1:
        raise InvalidInputError("No such authorization")
    await oauthserver.withdraw(session, user, grant_id)
    return Response(status_code=204)
