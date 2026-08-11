"""The operator's view of the instance.

Everything here is under ``/web/admin``, authenticates with the same cookie as
the rest of ``/web``, and is refused to anybody who does not administer the
instance. Nothing here is reachable with an API key: an instance administrator
is not a Zotero concept, and putting one in the v3 API would extend the API
where compatibility wins — see ``docs/compatibility.md``.

**An administrator counts and measures; they do not read.** No route here
answers with an item, a title, a tag, a note or a file, and the flag adds
nothing to :func:`altero.services.auth.user_access`: somebody administering the
instance has exactly the access to a library they had before. What they get is
what the instance costs, what state it is in, and the levers that belong to the
operator rather than to a library — which is the gap ``docs/motivation.md``
names, and which until now meant a shell on the server.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import API_VERSION, __version__
from altero.api.deps import SessionDep
from altero.api.routes import web
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import InvalidInputError, NotFoundError
from altero.models import ApiKey, GroupMember, User
from altero.services import (
    account,
    admin,
    emailverify,
    health,
    instancesettings,
    passwordreset,
    retention,
    storagestats,
    webauth,
)
from altero.services.mail import Message

router = APIRouter(prefix="/web/admin", tags=["web"])


async def get_administrator(user: CurrentUserDep) -> User:
    """Return the signed-in account, or refuse unless it administers this instance.

    403 rather than 404: the account is signed in and the screen exists, it is
    simply not theirs. Pretending otherwise would tell somebody who went
    looking that they had found a bug rather than a boundary.
    """
    if not user.administrator:
        raise HTTPException(status_code=403, detail="Only an administrator of this instance")
    return user


AdministratorDep = Annotated[User, Depends(get_administrator)]


class NewAccount(BaseModel):
    """What making an account for somebody else takes."""

    username: str
    password: str
    email: str = ""
    display_name: str = Field(default="", alias="displayName")
    administrator: bool = False
    #: The administrator's own, as everything that touches a credential takes.
    current_password: str = Field(default="", alias="currentPassword")


class AccountChange(BaseModel):
    """A change to somebody else's account. Each applied only when it is sent."""

    disabled: bool | None = None
    administrator: bool | None = None
    current_password: str = Field(default="", alias="currentPassword")


class NewPassword(BaseModel):
    password: str
    current_password: str = Field(default="", alias="currentPassword")


class PasswordOnly(BaseModel):
    current_password: str = Field(default="", alias="currentPassword")


def _serialise_account(user: User, *, keys: int = 0, groups: int = 0) -> dict:
    """Render one account for the list.

    Nothing about what is *in* their library, and no credential: an
    administrator counts and measures. The counts are what a decision to
    suspend or delete somebody is actually made from.
    """
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "email": user.email,
        "emailVerified": user.email_verified is not None,
        "administrator": user.administrator,
        "disabled": user.disabled_at is not None,
        "disabledAt": user.disabled_at.isoformat() + "Z" if user.disabled_at else None,
        "keys": keys,
        "groups": groups,
    }


async def _account(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("No such account")
    return user


def _library_usage(entry: storagestats.LibraryUsage) -> dict:
    """Render one library's usage. Numbers and a name, never its contents."""
    return {
        "id": entry.id,
        "type": entry.type.value,
        "ownerId": entry.owner_id,
        "name": entry.name,
        "version": entry.version,
        "items": entry.items,
        "trashed": entry.trashed,
        "collections": entry.collections,
        "tags": entry.tags,
        "attachments": entry.attachments,
        "files": entry.files,
        "bytes": entry.bytes,
        "missing": entry.missing,
    }


@router.get("/overview")
async def read_overview(
    request: Request, session: SessionDep, _admin: AdministratorDep
) -> Response:
    """Report what this instance is running and how much of everything it holds.

    The migration revision is here because "which migration is this instance
    on" is the question an upgrade asks, and reading it otherwise means a shell
    and `alembic current`. ``/health`` reports it too, and to anybody; this adds
    the counts, which are nobody else's business.

    The database is reported as its dialect and nothing more. The URL carries a
    password.
    """
    settings = request.app.state.settings
    usage = await storagestats.collect(session, settings.storage_path)

    return JSONResponse(
        {
            "version": __version__,
            "apiVersion": API_VERSION,
            "revision": await health.migration_revision(session),
            "database": settings.database_url.split("+")[0].split(":")[0],
            "users": usage.users,
            "libraries": len(usage.libraries),
            "groups": usage.groups,
            "storagePath": str(settings.storage_path),
            "nominalBytes": usage.nominal_bytes,
            "realBytes": usage.real_bytes,
            "savedBytes": usage.saved_bytes,
            "orphanBytes": usage.orphan_bytes,
            "orphanFiles": usage.orphan_files,
            "missingFiles": usage.missing_files,
        }
    )


def _settings_payload(values: dict[str, int], defaults: dict[str, int]) -> dict:
    """Report the settings in force, and what the deployment would give.

    Both, because a number on the screen means two different things depending
    on where it came from: an operator who set 30 days in `config.py` and one
    who typed it into this screen have made the same policy, and only the
    second survives a change to the file.
    """
    return {
        "settings": values,
        "defaults": defaults,
        "limits": {
            name: {"maximum": definition.maximum, "zero": definition.zero}
            for name, definition in instancesettings.DEFINITIONS.items()
        },
    }


@router.get("/settings")
async def read_settings(
    request: Request, session: SessionDep, _admin: AdministratorDep
) -> Response:
    """Report the retention periods in force."""
    settings = request.app.state.settings
    return JSONResponse(
        _settings_payload(
            await instancesettings.read_all(session, settings),
            {
                name: instancesettings.default(settings, name)
                for name in instancesettings.DEFINITIONS
            },
        )
    )


@router.put("/settings")
async def write_settings(
    request: Request,
    session: SessionDep,
    _admin: AdministratorDep,
    body: Annotated[dict[str, Any], Body()],
    _csrf: CsrfDep,
) -> Response:
    """Change one or more retention periods.

    No password, unlike the account's own screens: this changes a policy rather
    than a credential, and nothing here can be used to become somebody else.
    What it can do is delete things later on, which is why the periods are
    validated rather than stored as typed — see
    :mod:`altero.services.instancesettings`.
    """
    settings = request.app.state.settings
    values = await instancesettings.save(session, settings, body)
    return JSONResponse(
        _settings_payload(
            values,
            {
                name: instancesettings.default(settings, name)
                for name in instancesettings.DEFINITIONS
            },
        )
    )


@router.post("/retention/run")
async def run_retention(
    request: Request,
    session: SessionDep,
    _admin: AdministratorDep,
    _csrf: CsrfDep,
    preview: bool = False,
) -> Response:
    """Apply the retention periods now, or report what they would do.

    Here as well as on a timer because an operator setting a period for the
    first time wants to see what it will take before it takes it, and because
    an instance whose `retention_interval` is zero — the default — has nothing
    else that would ever run it.
    """
    values = await instancesettings.read_all(session, request.app.state.settings)
    report = await retention.sweep(session, values, dry_run=preview)

    return JSONResponse(
        {
            "preview": preview,
            "itemsDeleted": report.items_deleted,
            "libraries": report.libraries,
            "activity": report.activity,
            "uploads": report.uploads,
            "sessions": report.sessions,
            "verifications": report.verifications,
            "invitations": report.invitations,
            "summary": retention.describe(report),
        }
    )


@router.get("/users")
async def list_accounts(session: SessionDep, _admin: AdministratorDep) -> Response:
    """Report every account, with what a decision about it would be made from."""
    users = list(await session.scalars(select(User).order_by(User.id)))
    keys = {
        user_id: count
        for user_id, count in await session.execute(
            select(ApiKey.user_id, func.count()).group_by(ApiKey.user_id)
        )
    }
    groups = {
        user_id: count
        for user_id, count in await session.execute(
            select(GroupMember.user_id, func.count()).group_by(GroupMember.user_id)
        )
    }

    return JSONResponse(
        {
            "users": [
                _serialise_account(user, keys=keys.get(user.id, 0), groups=groups.get(user.id, 0))
                for user in users
            ]
        }
    )


@router.post("/users", status_code=201)
async def create_account(
    request: Request,
    session: SessionDep,
    admin_user: AdministratorDep,
    body: NewAccount,
    _csrf: CsrfDep,
) -> Response:
    """Make an account for somebody else, with a password to hand them.

    The password is set here rather than mailed, and the interface shows it
    once, the way `altero key add` shows a key once. Handing it over is the
    administrator's business; the person changes it in their own settings.

    An address is optional, exactly as it is for `altero user add`: an account
    syncs without one, and requiring one would make this refuse the case the
    command line has always allowed.
    """
    account.require_password(admin_user, body.current_password)

    user = await admin.create_user(
        session,
        username=webauth.validate_username(body.username),
        display_name=body.display_name or body.username,
    )
    if body.email:
        address = emailverify.normalise(body.email)
        if await session.scalar(
            select(User).where(func.lower(User.email) == address, User.id != user.id)
        ):
            # Checked after the account exists only because create_user assigns
            # the id; the account is removed again rather than left half-made.
            await admin.delete_user(session, user)
            raise InvalidInputError("That email address is already registered")
        user.email = address
        await session.commit()

    await webauth.set_password(session, user, body.password)
    if body.administrator:
        await admin.set_administrator(session, user, administrator=True)

    return JSONResponse({"user": _serialise_account(user)}, status_code=201)


@router.patch("/users/{user_id}")
async def change_account(
    session: SessionDep,
    admin_user: AdministratorDep,
    user_id: int,
    body: AccountChange,
    _csrf: CsrfDep,
) -> Response:
    """Suspend an account, put it back, or change who administers the instance.

    Neither can be done to yourself. Suspending yourself is a door that locks
    from the inside with the key still in it, and standing down is
    :func:`altero.services.admin.set_administrator`'s own refusal when you are
    the last one -- which it makes on behalf of the instance rather than of
    whoever clicked.
    """
    account.require_password(admin_user, body.current_password)
    user = await _account(session, user_id)

    if user.id == admin_user.id and body.disabled is not None:
        raise InvalidInputError("You cannot suspend yourself")

    if body.disabled is not None:
        await admin.set_disabled(session, user, disabled=body.disabled)
    if body.administrator is not None:
        await admin.set_administrator(session, user, administrator=body.administrator)

    return JSONResponse({"user": _serialise_account(user)})


@router.post("/users/{user_id}/password", status_code=204)
async def set_account_password(
    session: SessionDep,
    admin_user: AdministratorDep,
    user_id: int,
    body: NewPassword,
    _csrf: CsrfDep,
) -> Response:
    """Set somebody's password, ending their other sessions.

    The operation `docs/motivation.md` names as one of the two that most often
    sent somebody to a shell. Through the same
    :func:`altero.services.webauth.set_password` the command line uses, so the
    owner is told about it if there is a confirmed address to tell.
    """
    account.require_password(admin_user, body.current_password)
    user = await _account(session, user_id)

    await webauth.set_password(session, user, body.password)
    return Response(status_code=204)


@router.post("/users/{user_id}/reset")
async def issue_password_reset(
    request: Request,
    session: SessionDep,
    admin_user: AdministratorDep,
    user_id: int,
    body: PasswordOnly,
    _csrf: CsrfDep,
) -> Response:
    """Issue a link the account can set its own password from.

    The alternative to typing a password and telling somebody what it is, which
    leaves it known to two people. It is mailed where there is a confirmed
    address, and returned here either way — an instance with no relay
    configured is the ordinary case, and a link only readable in the server log
    would need the shell this screen exists to replace.
    """
    account.require_password(admin_user, body.current_password)
    user = await _account(session, user_id)

    token = await passwordreset.issue(session, user, issued_by=admin_user)
    link = web.reset_link(request, token)
    sent = False
    if emailverify.is_verified(user):
        sent = await request.app.state.mailer.send(
            Message(
                to=user.email or "",
                subject="Set a new password for altero",
                body=(
                    f"Hello {user.display_name or user.username},\n\n"
                    "Somebody who administers this altero server has asked you to "
                    "set a new password:\n\n"
                    f"    {link}\n\n"
                    f"The link is good for {passwordreset.LIFETIME_HOURS} hours and "
                    "can be used once. Until you follow it your current password "
                    "still works.\n"
                ),
            )
        )

    return JSONResponse({"link": link, "sent": sent, "hours": passwordreset.LIFETIME_HOURS})


@router.post("/users/{user_id}/revoke")
async def revoke_account_credentials(
    session: SessionDep,
    admin_user: AdministratorDep,
    user_id: int,
    body: PasswordOnly,
    _csrf: CsrfDep,
) -> Response:
    """Drop every key and every signed-in browser, leaving the account working."""
    account.require_password(admin_user, body.current_password)
    user = await _account(session, user_id)

    keys, sessions = await admin.revoke_credentials(session, user)
    return JSONResponse({"keys": keys, "sessions": sessions})


@router.delete("/users/{user_id}", status_code=204)
async def delete_account(
    session: SessionDep,
    admin_user: AdministratorDep,
    user_id: int,
    body: PasswordOnly,
    _csrf: CsrfDep,
) -> Response:
    """Remove an account and its personal library.

    The one route here that reaches into a library, and it does not read one:
    it goes through the same `clear_library` a group deletion uses. Refused
    while the account owns a group, and refused for yourself -- an
    administrator deleting their own account would take the instance's
    administration with it.
    """
    account.require_password(admin_user, body.current_password)
    user = await _account(session, user_id)

    if user.id == admin_user.id:
        raise InvalidInputError(
            "You cannot delete your own account here. Another administrator can."
        )

    await admin.delete_user(session, user)
    return Response(status_code=204)


@router.get("/storage")
async def read_storage(request: Request, session: SessionDep, _admin: AdministratorDep) -> Response:
    """Report what each library costs, and what does not add up.

    Nominal against real is the point of it: a file attached in two libraries
    is on disk once and in both libraries' accounts. See
    :mod:`altero.services.storagestats`.
    """
    usage = await storagestats.collect(session, request.app.state.settings.storage_path)

    return JSONResponse(
        {
            "libraries": [_library_usage(entry) for entry in usage.libraries],
            "nominalBytes": usage.nominal_bytes,
            "realBytes": usage.real_bytes,
            "savedBytes": usage.saved_bytes,
            "storedFiles": usage.stored_files,
            "storedBytes": usage.stored_bytes,
            "orphanFiles": usage.orphan_files,
            "orphanBytes": usage.orphan_bytes,
            "missingFiles": usage.missing_files,
        }
    )
