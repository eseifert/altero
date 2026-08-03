"""Linking a Zotero desktop client, from the browser.

The client starts a login session, opens ``loginURL`` in a browser and polls
until somebody has approved it. Upstream that page is zotero.org's own sign-in;
here it is this interface.

What gets handed over is a full-access API key -- a credential that reads and
writes every library the account can reach, and that outlives the browser
session entirely. That is a larger grant than signing in to read one's own
library, which is why approving takes the password again rather than trusting
the cookie: otherwise anyone who could get a signed-in person to open a link
they prepared would walk away with a permanent key. The CSRF token stops the
page being submitted from elsewhere; the password stops the link being useful
even if it is opened.

Declining takes no password. Refusing to grant something should never be harder
than granting it.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import LoginSession, User
from altero.services import admin, passwords
from altero.services import login as login_service

router = APIRouter(prefix="/web", tags=["web"])


class Approval(BaseModel):
    current_password: str = Field(alias="currentPassword")


async def _pending(session: SessionDep, token: str) -> LoginSession:
    """Return the session, translating the service's errors into HTTP ones."""
    try:
        return await login_service.get_session(session, token)
    except NotFoundError as missing:
        # Covers expiry too: SessionExpiredError is a NotFoundError, and an
        # expired session is gone as far as this flow is concerned.
        raise HTTPException(status_code=404, detail=missing.message) from missing


def _seconds_left(record: LoginSession) -> int:
    elapsed = datetime.now(UTC).replace(tzinfo=None) - record.created
    remaining = login_service.SESSION_LIFETIME_MINUTES * 60 - int(elapsed.total_seconds())
    return max(0, remaining)


async def _refusal(session: SessionDep, record: LoginSession, user: User) -> str | None:
    """Return why this person cannot approve this session, or ``None``.

    Worked out before anything is granted so the page can explain itself,
    rather than letting the attempt fail at the end with a bare error.
    """
    if record.status != login_service.PENDING:
        return f"This request has already been {record.status}."

    if record.requested_user_id is not None and record.requested_user_id != user.id:
        # The client said which account it expects. Handing it another user's
        # key makes the desktop application see a changed userID, offer to
        # reset its data directory and quit -- so it is refused here rather
        # than turned into a support request.
        expected = await session.get(User, record.requested_user_id)
        who = expected.username if expected else f"user {record.requested_user_id}"
        return f"This request is for the account “{who}”, not for yours."

    return None


@router.get("/link/{token}")
async def read_link_request(session: SessionDep, user: CurrentUserDep, token: str) -> Response:
    """Describe a pending client login, for the confirmation screen."""
    record = await _pending(session, token)
    reason = await _refusal(session, record, user)

    return JSONResponse(
        {
            "status": record.status,
            "requestedUserId": record.requested_user_id,
            "expiresInSeconds": _seconds_left(record),
            "canApprove": reason is None,
            "reason": reason,
        }
    )


@router.post("/link/{token}/approve", status_code=204)
async def approve_link_request(
    session: SessionDep,
    user: CurrentUserDep,
    token: str,
    body: Annotated[Approval, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Issue a key for this account and complete the client's login."""
    record = await _pending(session, token)

    if not passwords.verify_password(user.password_hash, body.current_password):
        raise ForbiddenError("That password is not correct")

    reason = await _refusal(session, record, user)
    if reason is not None:
        raise InvalidInputError(reason)

    # Full access, including groups: this is the credential the desktop
    # application syncs with, and a key that omitted group libraries would
    # present as a server that had lost them.
    api_key = await admin.create_api_key(
        session,
        username=user.username,
        name=login_service.KEY_NAME,
        read=True,
        write=True,
        notes=True,
        files=True,
        all_groups_read=True,
        all_groups_write=True,
    )
    await login_service.approve_session(session, token, api_key)
    return Response(status_code=204)


@router.post("/link/{token}/deny", status_code=204)
async def deny_link_request(
    session: SessionDep, user: CurrentUserDep, token: str, _csrf: CsrfDep
) -> Response:
    """Refuse the request, so the client stops waiting instead of timing out."""
    await _pending(session, token)
    await login_service.cancel_session(session, token)
    return Response(status_code=204)
