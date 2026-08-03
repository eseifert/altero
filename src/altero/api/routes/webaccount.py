"""Account settings, notifications and invitations, for the browser.

Same rules as the rest of ``/web``: cookie only, never an API key, and a CSRF
token on anything that changes something. On top of that, every endpoint here
that touches a credential takes the current password as well -- see
:mod:`altero.services.account` for why a cookie alone is not enough.
"""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.routes.web import (
    AuthenticatedDep,
    CsrfDep,
    CurrentUserDep,
    _send_verification,
    _serialise,
)
from altero.errors import NotFoundError
from altero.models import ApiKey, Invitation, Library, Notification, User
from altero.services import account, invitations, notifications

router = APIRouter(prefix="/web", tags=["web"])


class DisplayName(BaseModel):
    display_name: str = Field(alias="displayName")


class PasswordChange(BaseModel):
    current_password: str = Field(alias="currentPassword")
    new_password: str = Field(alias="newPassword")


class EmailChange(BaseModel):
    email: str
    current_password: str = Field(alias="currentPassword")


class Confirmation(BaseModel):
    code: str


class PasswordOnly(BaseModel):
    current_password: str = Field(alias="currentPassword")


class NewKey(BaseModel):
    name: str
    current_password: str = Field(alias="currentPassword")
    write: bool = True
    groups: bool = True


class InviteRequest(BaseModel):
    email: str
    role: str = "member"


def _serialise_session(record, current_id: int) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": record.id,
        "userAgent": record.user_agent,
        "created": record.created.isoformat() + "Z",
        "lastSeen": record.last_seen.isoformat() + "Z",
        # So the interface can say "this device" rather than inviting someone
        # to sign themselves out without realising.
        "current": record.id == current_id,
    }


def _serialise_key(record: ApiKey) -> dict:
    """Render a key for the list, without the key.

    Only the last four characters. altero stores keys as it receives them, so
    the whole value could be shown -- which is exactly why it is not: doing so
    would turn a signed-in browser tab into a way of reading back every
    long-lived credential the account has, and the interface promises the same
    thing `altero key add` does, that the value is shown once.
    """
    return {
        "id": record.id,
        "name": record.name,
        "suffix": record.key[-4:],
        "created": record.created.isoformat() + "Z" if record.created else None,
        "lastUsed": record.last_used.isoformat() + "Z" if record.last_used else None,
        "lastAddress": record.last_address,
        "lastUserAgent": record.last_user_agent,
        "access": {
            "library": record.library_read,
            "write": record.library_write,
            "notes": record.notes_read,
            "files": record.files_read,
            "groups": record.all_groups_read,
            "groupsWrite": record.all_groups_write,
        },
    }


def _serialise_notification(record: Notification) -> dict:
    return {
        "id": record.id,
        "kind": record.kind,
        "subject": record.subject,
        "body": record.body,
        "invitationId": record.invitation_id,
        "created": record.created.isoformat() + "Z",
        "read": record.read is not None,
    }


async def _serialise_invitation(session: AsyncSession, record: Invitation) -> dict:
    library = await session.get(Library, record.library_id)
    inviter = await session.get(User, record.invited_by)
    return {
        "id": record.id,
        "libraryId": record.library_id,
        "libraryName": library.name if library else "",
        "role": record.role,
        "invitedBy": (inviter.display_name or inviter.username) if inviter else "",
        "status": record.status,
        "created": record.created.isoformat() + "Z",
        "expires": record.expires.isoformat() + "Z",
    }


# --------------------------------------------------------------------------
# The account itself
# --------------------------------------------------------------------------


@router.get("/account")
async def read_account(
    session: SessionDep, user: CurrentUserDep, record: AuthenticatedDep
) -> Response:
    """Everything the settings screen shows in one request."""
    return JSONResponse(
        {
            "user": _serialise(user),
            "totpEnabled": await account.is_totp_active(session, user),
            "sessions": [
                _serialise_session(entry, record.id)
                for entry in await account.list_sessions(session, user)
            ],
        }
    )


@router.patch("/account")
async def update_account(
    session: SessionDep, user: CurrentUserDep, body: DisplayName, _csrf: CsrfDep
) -> Response:
    await account.set_display_name(session, user, body.display_name)
    return JSONResponse({"user": _serialise(user)})


@router.post("/account/password", status_code=204)
async def change_password(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    record: AuthenticatedDep,
    body: PasswordChange,
    _csrf: CsrfDep,
) -> Response:
    await account.change_password(
        session,
        user,
        current_password=body.current_password,
        new_password=body.new_password,
        keep=record,
        notify=request.app.state.mailer.send,
    )
    return Response(status_code=204)


@router.post("/account/email", status_code=202)
async def change_email(
    request: Request, session: SessionDep, user: CurrentUserDep, body: EmailChange, _csrf: CsrfDep
) -> Response:
    """Begin moving the account to another address.

    202: the address has not changed yet and will not until the link sent to it
    is followed.
    """
    await account.request_email_change(
        session, user, new_email=body.email, current_password=body.current_password
    )
    # Re-issued by _send_verification so that the mail carries the token; the
    # call above has already checked the password and the address.
    await _send_verification(request, session, user, body.email)
    return JSONResponse({"pending": body.email.strip().lower()}, status_code=202)


@router.post("/account/totp", status_code=201)
async def begin_totp(session: SessionDep, user: CurrentUserDep, _csrf: CsrfDep) -> Response:
    """Start enrolling an authenticator. Not yet required at sign-in."""
    enrolment = await account.begin_totp_enrolment(session, user)
    return JSONResponse({"secret": enrolment.secret, "uri": enrolment.uri}, status_code=201)


@router.post("/account/totp/confirm", status_code=204)
async def confirm_totp(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    body: Confirmation,
    _csrf: CsrfDep,
) -> Response:
    await account.confirm_totp_enrolment(
        session, user, body.code, notify=request.app.state.mailer.send
    )
    return Response(status_code=204)


@router.post("/account/totp/disable", status_code=204)
async def disable_totp(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    body: PasswordOnly,
    _csrf: CsrfDep,
) -> Response:
    await account.disable_totp(
        session,
        user,
        current_password=body.current_password,
        notify=request.app.state.mailer.send,
    )
    return Response(status_code=204)


@router.delete("/account/sessions/{session_id}", status_code=204)
async def revoke_session(
    session: SessionDep,
    user: CurrentUserDep,
    record: AuthenticatedDep,
    session_id: int,
    _csrf: CsrfDep,
) -> Response:
    await account.revoke_session(session, user, session_id, current=record)
    return Response(status_code=204)


@router.post("/account/sessions/revoke-others", status_code=204)
async def revoke_other_sessions(
    session: SessionDep, user: CurrentUserDep, record: AuthenticatedDep, _csrf: CsrfDep
) -> Response:
    await account.revoke_other_sessions(session, user, keep=record)
    return Response(status_code=204)


@router.get("/account/keys")
async def list_keys(session: SessionDep, user: CurrentUserDep) -> Response:
    """List this account's API keys, masked."""
    return JSONResponse(
        {"keys": [_serialise_key(entry) for entry in await account.list_keys(session, user)]}
    )


@router.post("/account/keys", status_code=201)
async def create_key(
    session: SessionDep, user: CurrentUserDep, body: NewKey, _csrf: CsrfDep
) -> Response:
    """Issue a key and return it in full, this once.

    The only response that ever carries a whole key. Everything afterwards --
    including the list above -- shows four characters.
    """
    created = await account.create_key(
        session,
        user,
        name=body.name,
        current_password=body.current_password,
        write=body.write,
        groups=body.groups,
    )
    return JSONResponse({"key": created.key, "created": _serialise_key(created)}, status_code=201)


@router.delete("/account/keys/{key_id}", status_code=204)
async def revoke_key(
    session: SessionDep, user: CurrentUserDep, key_id: int, _csrf: CsrfDep
) -> Response:
    """Delete a key. No password: a leaked key has to be killable at once."""
    await account.revoke_key(session, user, key_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------


@router.get("/notifications")
async def list_notifications(
    session: SessionDep,
    user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=notifications.DEFAULT_LIMIT)] = 20,
) -> Response:
    return JSONResponse(
        {
            "unread": await notifications.unread_count(session, user),
            "notifications": [
                _serialise_notification(entry)
                for entry in await notifications.list_for(session, user, limit=limit)
            ],
            "invitations": [
                await _serialise_invitation(session, entry)
                for entry in await invitations.pending_for_user(session, user)
            ],
        }
    )


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_read(
    session: SessionDep, user: CurrentUserDep, notification_id: int, _csrf: CsrfDep
) -> Response:
    record = await session.get(Notification, notification_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such notification")
    await notifications.mark_read(session, record, user)
    return Response(status_code=204)


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(session: SessionDep, user: CurrentUserDep, _csrf: CsrfDep) -> Response:
    await notifications.mark_all_read(session, user)
    return Response(status_code=204)


# --------------------------------------------------------------------------
# Invitations
# --------------------------------------------------------------------------


async def _invitation_or_404(session: AsyncSession, invitation_id: int) -> Invitation:
    record = await session.get(Invitation, invitation_id)
    if record is None:
        raise NotFoundError("No such invitation")
    return record


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(
    session: SessionDep, user: CurrentUserDep, invitation_id: int, _csrf: CsrfDep
) -> Response:
    record = await _invitation_or_404(session, invitation_id)
    await invitations.accept(session, record, user)
    return JSONResponse({"invitation": await _serialise_invitation(session, record)})


@router.post("/invitations/{invitation_id}/decline")
async def decline_invitation(
    session: SessionDep, user: CurrentUserDep, invitation_id: int, _csrf: CsrfDep
) -> Response:
    record = await _invitation_or_404(session, invitation_id)
    await invitations.decline(session, record, user)
    return JSONResponse({"invitation": await _serialise_invitation(session, record)})


@router.post("/libraries/{library_id}/invitations", status_code=201)
async def invite_to_library(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    body: Annotated[InviteRequest, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Invite an address to a group library. Administrators only."""
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")

    record, token = await invitations.invite_with_token(
        session, library=library, inviter=user, email=body.email, role=body.role
    )

    base = request.app.state.settings.public_url.rstrip("/") or str(request.base_url).rstrip("/")
    await request.app.state.mailer.send(
        _invitation_message(record, library, user, f"{base}/app/invitations?token={token}")
    )
    return JSONResponse(
        {"invitation": await _serialise_invitation(session, record)}, status_code=201
    )


def _invitation_message(record: Invitation, library: Library, inviter: User, link: str):  # type: ignore[no-untyped-def]
    from altero.services.mail import Message

    who = inviter.display_name or inviter.username
    return Message(
        to=record.email,
        subject=f"{who} invited you to “{library.name}” on altero",
        body=(
            f"{who} has invited you to join the group library “{library.name}” "
            f"as {'an administrator' if record.role == 'admin' else 'a member'}.\n\n"
            f"    {link}\n\n"
            "If you already have an account here, the invitation is also "
            "waiting in your notifications.\n"
        ),
    )


@router.get("/libraries/{library_id}/invitations")
async def list_library_invitations(
    session: SessionDep, user: CurrentUserDep, library_id: int
) -> Response:
    """Outstanding invitations for a group. Administrators only."""
    library = await session.get(Library, library_id)
    if library is None:
        raise NotFoundError("No such library")
    await invitations.require_admin(session, library, user)

    return JSONResponse(
        {
            "invitations": [
                await _serialise_invitation(session, entry)
                for entry in await invitations.pending_for_library(session, library)
            ]
        }
    )
