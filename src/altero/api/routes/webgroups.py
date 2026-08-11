"""Groups, for the browser.

Same rules as the rest of ``/web``: cookie only, never an API key, and a CSRF
token on anything that changes something. The decisions themselves live in
:mod:`altero.services.groups`, which is what the v3 API's group endpoints go
through as well, so a role means the same thing whichever door it was set
from -- and there is one place to read to find out what it means.

What differs from the v3 endpoints is the address. The interface holds a flat
list of libraries by their internal id, as the rest of ``/web`` does, rather
than the ``/groups/<groupID>`` prefix a sync client is written against.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response

from altero import serializers
from altero.api.deps import SessionDep
from altero.api.routes.web import CsrfDep, CurrentUserDep
from altero.errors import InvalidInputError, NotFoundError
from altero.models import (
    ActivityKind,
    Group,
    GroupMember,
    Invitation,
    Item,
    Library,
    LibraryType,
    User,
)
from altero.services import auth, grouplog, groupprefs, groups, invitations, writes

router = APIRouter(prefix="/web", tags=["web"])


class GroupWrite(BaseModel):
    """The properties the interface offers. A subset on purpose: ``url`` is
    upstream's link to a group's page on zotero.org, which has no meaning here.
    """

    name: str | None = None
    description: str | None = None
    type: str | None = None
    library_reading: str | None = Field(default=None, alias="libraryReading")
    library_editing: str | None = Field(default=None, alias="libraryEditing")
    file_editing: str | None = Field(default=None, alias="fileEditing")

    def payload(self) -> dict[str, Any]:
        """Return the properties that were actually sent."""
        return self.model_dump(by_alias=True, exclude_none=True)


class MembershipChange(BaseModel):
    """What a member's row can be changed to. Either half, or both.

    Two properties rather than one because they answer different questions --
    a role says whether somebody helps run the group, a permission says how far
    they may go in it -- and a form that had to send both to change one would
    keep overwriting the other.
    """

    role: str | None = None
    permission: str | None = None


async def _group(session: AsyncSession, library_id: int) -> tuple[Library, Group]:
    library = await session.get(Library, library_id)
    if library is None or library.type is not LibraryType.GROUP:
        raise NotFoundError("No such group")
    return library, await groups.get_group(session, library)


async def _member_of(session: AsyncSession, library: Library, user: User) -> GroupMember:
    """Return the caller's membership, or refuse.

    A group somebody is not in answers 404 rather than 403, as the v3 endpoint
    does: a stranger learns nothing about which private groups exist.
    """
    member = await groups.membership(session, library, user.id)
    if member is None:
        raise NotFoundError("No such group")
    return member


async def _serialise(
    session: AsyncSession, library: Library, group: Group, member: GroupMember
) -> dict[str, Any]:
    """Render a group as the interface shows it."""
    members = await session.scalar(
        select(func.count()).select_from(GroupMember).where(GroupMember.library_id == library.id)
    )
    items = await session.scalar(
        select(func.count())
        .select_from(Item)
        .where(Item.library_id == library.id, Item.deleted.is_(False))
    )

    return {
        "id": library.id,
        "groupId": library.owner_id,
        "name": group.name,
        "description": group.description,
        "type": group.type,
        "libraryReading": group.library_reading,
        # The group's own policy, unnarrowed. This is the settings form: an
        # administrator has to see what they set, and a restricted member has to
        # see what the group says before their own restriction is applied to it.
        # `permission` beside it is the narrowing, said separately.
        "libraryEditing": group.library_editing,
        "fileEditing": group.file_editing,
        "version": library.version,
        # What this account may do here, so the interface can decide what to
        # draw rather than offering buttons the server will refuse.
        "role": member.role,
        "permission": auth.member_permission(member),
        "owner": group.owner_id == member.user_id,
        "ownerId": group.owner_id,
        "numMembers": members or 0,
        "numItems": items or 0,
    }


#: The name each activity kind carries in the browser's JSON. The wire names
#: are camelCase like the rest of ``/web``; the stored ones are the enum's.
_NOTIFICATION_NAMES: dict[ActivityKind, str] = {
    ActivityKind.ITEMS_CHANGED: "itemsChanged",
    ActivityKind.ITEMS_DELETED: "itemsDeleted",
    ActivityKind.MEMBERS_CHANGED: "membersChanged",
    ActivityKind.COLLECTIONS_CHANGED: "collectionsChanged",
}


class NotificationWrite(BaseModel):
    """Which kinds to change. Omitting one leaves it as it was.

    A partial write on purpose: the panel sends the toggle that moved rather
    than all four, so two open tabs cannot undo each other's choices.
    """

    items_changed: bool | None = Field(default=None, alias="itemsChanged")
    items_deleted: bool | None = Field(default=None, alias="itemsDeleted")
    members_changed: bool | None = Field(default=None, alias="membersChanged")
    collections_changed: bool | None = Field(default=None, alias="collectionsChanged")

    def wanted(self) -> dict[ActivityKind, bool]:
        """Return only the kinds this request named."""
        named = {
            ActivityKind.ITEMS_CHANGED: self.items_changed,
            ActivityKind.ITEMS_DELETED: self.items_deleted,
            ActivityKind.MEMBERS_CHANGED: self.members_changed,
            ActivityKind.COLLECTIONS_CHANGED: self.collections_changed,
        }
        return {kind: value for kind, value in named.items() if value is not None}


async def _notification_payload(
    session: AsyncSession, library: Library, user_id: int
) -> dict[str, bool]:
    held = await groupprefs.get(session, library, user_id=user_id)
    return {_NOTIFICATION_NAMES[kind]: value for kind, value in held.items()}


def _member_payload(user: User, member: GroupMember, owner_id: int) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": member.role,
        "permission": auth.member_permission(member),
        "owner": user.id == owner_id,
    }


@router.get("/groups")
async def list_groups(session: SessionDep, user: CurrentUserDep) -> Response:
    """Return every group this account belongs to."""
    payload = []
    for library, group, member in await groups.list_groups_for_user(session, user.id):
        payload.append(await _serialise(session, library, group, member))

    return JSONResponse({"groups": payload})


@router.post("/groups", status_code=201)
async def create_group(
    session: SessionDep,
    user: CurrentUserDep,
    body: Annotated[GroupWrite, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Create a group owned by this account.

    Open to anybody signed in. A group is a library of your own, made from your
    own quota of nothing in particular; refusing it would mean deciding who is
    allowed collaborators, which is not something this server knows.
    """
    library, group = await groups.create_group(session, owner=user, payload=body.payload())
    await session.commit()

    member = await groups.membership(session, library, user.id)
    assert member is not None
    return JSONResponse(await _serialise(session, library, group, member), status_code=201)


@router.get("/groups/{library_id}")
async def read_group(session: SessionDep, user: CurrentUserDep, library_id: int) -> Response:
    """Return one group, with the members and invitations an admin may see."""
    library, group = await _group(session, library_id)
    member = await _member_of(session, library, user)

    payload = await _serialise(session, library, group, member)
    payload["members"] = [
        _member_payload(entry, membership, group.owner_id)
        for entry, membership in await groups.list_members(session, library)
    ]
    # Only an administrator hands membership out, so only an administrator is
    # shown who has been offered it.
    payload["invitations"] = (
        [
            {
                "id": record.id,
                "email": record.email,
                "role": record.role,
                "permission": record.permission,
                "expires": record.expires.isoformat() + "Z",
            }
            for record in await invitations.pending_for_library(session, library)
        ]
        if member.role == "admin"
        else []
    )
    # Carried here as well as on its own endpoint, so the settings panel draws
    # in one request rather than two.
    payload["notifications"] = await _notification_payload(session, library, user.id)
    return JSONResponse(payload)


def _as_int(value: str | None, default: int) -> int:
    """Return ``value`` as an integer, or ``default`` if it is not one."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


@router.get("/groups/{library_id}/activity")
async def read_activity(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    limit: str | None = None,
    start: str | None = None,
) -> Response:
    """Return what has happened in this group, newest first.

    Every member sees it, not only administrators. It was asked for as a way of
    keeping up with a shared library; restricting it to the people who run the
    group would make it a supervision tool instead.

    ``limit`` and ``start`` are taken as strings and parsed leniently, because
    an unreadable number is ignored everywhere else this server takes one --
    see the parameter-handling section of ``docs/compatibility.md``. Declaring
    them as integers would make FastAPI answer ``422`` and put one corner of
    the interface out of step with the rest of the server.
    """
    library, _ = await _group(session, library_id)
    await _member_of(session, library, user)

    page = await grouplog.read(
        session,
        library,
        limit=_as_int(limit, grouplog.DEFAULT_LIMIT),
        start=_as_int(start, 0),
    )
    return JSONResponse(
        {
            "activity": [
                {
                    "id": entry.id,
                    "kind": entry.kind,
                    "count": entry.count,
                    "when": serializers.timestamp(entry.when),
                    "actor": serializers.user_block(entry.actor) if entry.actor else None,
                    "objects": [
                        {"key": touched.key, "name": touched.name} for touched in entry.objects
                    ],
                }
                for entry in page.entries
            ],
            "total": page.total,
        }
    )


@router.get("/groups/{library_id}/notifications")
async def read_notifications(
    session: SessionDep, user: CurrentUserDep, library_id: int
) -> Response:
    """Return what this account has asked to be told about in this group."""
    library, _ = await _group(session, library_id)
    await _member_of(session, library, user)

    return JSONResponse(await _notification_payload(session, library, user.id))


@router.put("/groups/{library_id}/notifications")
async def set_notifications(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    body: Annotated[NotificationWrite, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Change what this account is told about in this group.

    Your own only. There is no address to point somebody else's notifications
    at, and a group's administrator deciding what its members are mailed about
    is not a power anyone asked for.
    """
    library, _ = await _group(session, library_id)
    await _member_of(session, library, user)

    for kind, wanted in body.wanted().items():
        await groupprefs.set_kind(session, library, user_id=user.id, kind=kind, wanted=wanted)
    await session.commit()

    return JSONResponse(await _notification_payload(session, library, user.id))


@router.patch("/groups/{library_id}")
async def update_group(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    body: Annotated[GroupWrite, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Change a group's metadata. Administrators only."""
    library, group = await _group(session, library_id)
    await groups.require_admin(session, library, user.id)

    library = await writes.lock_library(session, library)
    await groups.update_group(session, library, group, body.payload(), actor=user, replace=False)
    await writes.bump_library_version(session, library)
    await session.commit()

    member = await groups.membership(session, library, user.id)
    assert member is not None
    return JSONResponse(await _serialise(session, library, group, member))


@router.delete("/groups/{library_id}", status_code=204)
async def delete_group(
    session: SessionDep, user: CurrentUserDep, library_id: int, _csrf: CsrfDep
) -> Response:
    """Delete a group and everything in it. The owner only."""
    library, _ = await _group(session, library_id)
    await _member_of(session, library, user)
    await groups.require_owner(session, library, user.id)

    await groups.delete_group(session, library)
    await session.commit()
    return Response(status_code=204)


@router.put("/groups/{library_id}/members/{member_id}")
async def set_member_role(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    member_id: int,
    body: Annotated[MembershipChange, Body()],
    _csrf: CsrfDep,
) -> Response:
    """Change one member's role, their permission, or both. Administrators only.

    The library version moves, as it does for every membership change: a member
    who has just been made read-only is told so by their client asking for the
    group again, and it asks because the version moved.
    """
    library, group = await _group(session, library_id)
    await groups.require_admin(session, library, user.id)

    subject = await session.get(User, member_id)
    if subject is None:
        raise NotFoundError("No such user")
    if body.role is None and body.permission is None:
        raise InvalidInputError("Nothing to change")

    library = await writes.lock_library(session, library)
    # Role first: promoting somebody clears their permission, so a request
    # carrying both ends on the permission it asked for.
    member = None
    if body.role is not None:
        member = await groups.set_role(session, library, subject, body.role)
    if body.permission is not None:
        member = await groups.set_permission(session, library, subject, body.permission)
    assert member is not None

    await writes.bump_library_version(session, library)
    await session.commit()

    return JSONResponse(_member_payload(subject, member, group.owner_id))


@router.delete("/groups/{library_id}/members/{member_id}", status_code=204)
async def remove_member(
    session: SessionDep, user: CurrentUserDep, library_id: int, member_id: int, _csrf: CsrfDep
) -> Response:
    """Remove a member, or leave the group.

    An administrator may remove anybody but the owner; anybody may remove
    themselves without asking, because a member who needed permission to leave
    would be in a group they cannot get out of.
    """
    library, _ = await _group(session, library_id)
    await _member_of(session, library, user)
    if user.id != member_id:
        await groups.require_admin(session, library, user.id)

    subject = await session.get(User, member_id)
    if subject is None:
        raise NotFoundError("No such user")

    library = await writes.lock_library(session, library)
    await groups.remove_member(session, library, subject)
    await writes.bump_library_version(session, library)
    await session.commit()
    return Response(status_code=204)


@router.post("/groups/{library_id}/transfer", status_code=204)
async def transfer_group(
    session: SessionDep,
    user: CurrentUserDep,
    library_id: int,
    body: Annotated[dict[str, Any], Body()],
    _csrf: CsrfDep,
) -> Response:
    """Hand the group to another member. The owner only.

    A route of its own rather than a property of the metadata form, because it
    is not a setting: it is the one change the person making it cannot undo.
    """
    library, group = await _group(session, library_id)
    await groups.require_owner(session, library, user.id)

    successor = body.get("userID")
    if not isinstance(successor, int):
        raise InvalidInputError("A user id is required")

    library = await writes.lock_library(session, library)
    await groups.update_group(
        session, library, group, {"owner": successor}, actor=user, replace=False
    )
    await writes.bump_library_version(session, library)
    await session.commit()
    return Response(status_code=204)


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    session: SessionDep, user: CurrentUserDep, invitation_id: int, _csrf: CsrfDep
) -> Response:
    """Withdraw an invitation nobody has answered. Administrators only."""
    record = await session.get(Invitation, invitation_id)
    if record is None:
        raise NotFoundError("No such invitation")

    await invitations.revoke(session, record, user)
    return Response(status_code=204)


@router.get("/invitations/token/{token}")
async def read_invitation(session: SessionDep, token: str) -> Response:
    """Describe the invitation an emailed link identifies.

    Deliberately needs no session: the link is followed in whichever browser is
    open, which is frequently not one that is signed in, and the token in it is
    the whole credential. What comes back is enough to decide what to show --
    which group, at what role, and whether the address already has an account
    here -- and nothing that would tell a guesser anything about the instance.
    """
    record = await invitations.by_token(session, token)
    library = await session.get(Library, record.library_id)
    inviter = await session.get(User, record.invited_by)
    registered = await session.scalar(select(User).where(User.email == record.email))

    return JSONResponse(
        {
            "id": record.id,
            "libraryName": library.name if library else "",
            "email": record.email,
            "role": record.role,
            "permission": record.permission,
            "status": record.status,
            "expires": record.expires.isoformat() + "Z",
            "invitedBy": (inviter.display_name or inviter.username) if inviter else "",
            # Decides whether the link offers a sign-in or a registration form.
            "hasAccount": registered is not None,
        }
    )


@router.post("/invitations/token/{token}/{decision}")
async def answer_invitation(
    session: SessionDep, user: CurrentUserDep, token: str, decision: str, _csrf: CsrfDep
) -> Response:
    """Accept or decline from the emailed link, once signed in.

    The token identifies the invitation; who may answer it is still decided by
    the address it was sent to, in :mod:`altero.services.invitations`. Holding
    the link is not the same as being the person it was offered to.
    """
    if decision not in ("accept", "decline"):
        raise InvalidInputError("A decision must be accept or decline")

    record = await invitations.by_token(session, token)
    if decision == "accept":
        await invitations.accept(session, record, user)
    else:
        await invitations.decline(session, record, user)

    return JSONResponse({"status": record.status, "libraryId": record.library_id})


@router.get("/groups/{library_id}/members")
async def list_members(session: SessionDep, user: CurrentUserDep, library_id: int) -> Response:
    """Return the group's members. Members only."""
    library, group = await _group(session, library_id)
    await _member_of(session, library, user)

    return JSONResponse(
        {
            "members": [
                _member_payload(entry, membership, group.owner_id)
                for entry, membership in await groups.list_members(session, library)
            ]
        }
    )
