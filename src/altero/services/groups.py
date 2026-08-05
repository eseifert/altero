"""Group libraries: their metadata, their membership and their lifetime.

Upstream keeps all of this behind a superuser credential that no API key can
present, so there is no reference implementation for the rules below -- only
for the shape of a group, which ``GET /groups/<id>`` publishes and which is
what a write here accepts back. ``docs/compatibility.md`` records where that
leaves altero.

Two ideas run through it. **Administering a group is not the same as writing to
it**: a member may add items and still not decide who else can. And **the owner
is one of the admins, not a fourth role**: what the owner alone may do is hand
the group over and destroy it, both of which end the group as everybody else
knows it.
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import (
    ApiKeyGroupAccess,
    Group,
    GroupActivity,
    GroupMember,
    Invitation,
    Library,
    LibraryType,
    StorageUpload,
    User,
    WriteToken,
)
from altero.services import streaming

#: What a group may be. Zotero's own three: private, and two public kinds that
#: differ in whether anyone may join or must be invited.
GROUP_TYPES = ("Private", "PublicOpen", "PublicClosed")

#: Who may change the library's contents.
LIBRARY_EDITING = ("members", "admins")

#: Who may read them. ``all`` is what makes a group library public.
LIBRARY_READING = ("all", "members")

#: Who may upload and replace attachment files.
FILE_EDITING = ("none", "members", "admins")

#: Roles a member may hold.
ROLES = ("member", "admin")

#: Longest a group name may be, matching the column.
MAX_NAME = 255

#: Every property a group carries, with the values each accepts. ``None`` means
#: free text.
_PROPERTIES: dict[str, tuple[str, ...] | None] = {
    "name": None,
    "description": None,
    "url": None,
    "type": GROUP_TYPES,
    "libraryEditing": LIBRARY_EDITING,
    "libraryReading": LIBRARY_READING,
    "fileEditing": FILE_EDITING,
}

#: The column each property is stored in.
_COLUMNS = {
    "name": "name",
    "description": "description",
    "url": "url",
    "type": "type",
    "libraryEditing": "library_editing",
    "libraryReading": "library_reading",
    "fileEditing": "file_editing",
}

#: What a property becomes when a replacing write leaves it out. ``name`` is
#: absent because a group must have one, so leaving it out is an error rather
#: than a reset.
_DEFAULTS = {
    "description": "",
    "url": "",
    "type": "Private",
    "libraryEditing": "members",
    "libraryReading": "members",
    "fileEditing": "members",
}


async def get_group(session: AsyncSession, library: Library) -> Group:
    """Return the metadata of a group library.

    Raises:
        NotFoundError: The library is a group with no metadata row, which a
            correctly provisioned instance does not have.
    """
    group = await session.scalar(select(Group).where(Group.library_id == library.id))
    if group is None:
        raise NotFoundError("Group not found")
    return group


async def list_public_libraries(session: AsyncSession) -> list[Library]:
    """Return every library readable without a credential.

    What an anonymous streaming connection may watch, which is exactly what an
    anonymous request may read.
    """
    result = await session.scalars(
        select(Library).where(Library.public.is_(True)).order_by(Library.id)
    )
    return list(result)


async def list_groups_for_user(
    session: AsyncSession,
    user_id: int,
) -> list[tuple[Library, Group]]:
    """Return the group libraries ``user_id`` belongs to, with their metadata."""
    statement = (
        select(Library, Group)
        .join(Group, Group.library_id == Library.id)
        .join(GroupMember, GroupMember.library_id == Library.id)
        .where(GroupMember.user_id == user_id, Library.type == LibraryType.GROUP)
        .order_by(Library.owner_id)
    )
    result = await session.execute(statement)
    return [(library, group) for library, group in result.all()]


# --------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------


async def membership(session: AsyncSession, library: Library, user_id: int) -> GroupMember | None:
    return await session.scalar(
        select(GroupMember).where(
            GroupMember.library_id == library.id, GroupMember.user_id == user_id
        )
    )


async def require_admin(session: AsyncSession, library: Library, user_id: int) -> GroupMember:
    """Raise unless ``user_id`` administers ``library``.

    Membership and the ability to hand membership out are different things: a
    group where every member can add anyone is a group nobody can keep track
    of.
    """
    if library.type is not LibraryType.GROUP:
        raise InvalidInputError("Only a group library has members")

    held = await membership(session, library, user_id)
    if held is None or held.role != "admin":
        raise ForbiddenError("Only an administrator of this group can do that")
    return held


async def require_owner(session: AsyncSession, library: Library, user_id: int) -> Group:
    """Raise unless ``user_id`` owns ``library``.

    Kept apart from :func:`require_admin` for the two things that end the group
    as its members know it: giving it away and deleting it.
    """
    group = await get_group(session, library)
    if group.owner_id != user_id:
        raise ForbiddenError("Only the owner of this group can do that")
    return group


async def list_members(session: AsyncSession, library: Library) -> list[tuple[User, GroupMember]]:
    """Return the group's members with the accounts behind them."""
    result = await session.execute(
        select(User, GroupMember)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.library_id == library.id)
        .order_by(GroupMember.user_id)
    )
    return [(user, member) for user, member in result.all()]


async def add_member(
    session: AsyncSession, library: Library, user: User, role: str = "member"
) -> GroupMember:
    """Add ``user`` to ``library`` at ``role``."""
    _check_role(role)
    if await membership(session, library, user.id) is not None:
        raise InvalidInputError(f"'{user.username}' is already a member")

    member = GroupMember(library_id=library.id, user_id=user.id, role=role)
    session.add(member)
    streaming.note_access_change(session.sync_session, user.id)
    return member


async def set_role(session: AsyncSession, library: Library, user: User, role: str) -> GroupMember:
    """Change what ``user`` may do in ``library``.

    The owner's own role is fixed at admin. Demoting them would leave a group
    whose owner cannot administer it, and only a transfer of ownership should
    be able to produce that.
    """
    _check_role(role)
    group = await get_group(session, library)

    member = await membership(session, library, user.id)
    if member is None:
        raise NotFoundError(f"'{user.username}' is not a member of this group")
    if group.owner_id == user.id and role != "admin":
        raise InvalidInputError("The owner of a group is always an administrator")

    member.role = role
    return member


async def remove_member(session: AsyncSession, library: Library, user: User) -> None:
    """Take ``user`` out of ``library``.

    The owner cannot be removed. Somebody has to be able to answer for the
    group, and a group with no owner has nobody who can delete it or hand it
    on.
    """
    group = await get_group(session, library)
    if group.owner_id == user.id:
        raise InvalidInputError(
            "The owner cannot be removed; transfer the group first, or delete it"
        )

    member = await membership(session, library, user.id)
    if member is None:
        raise NotFoundError(f"'{user.username}' is not a member of this group")

    await session.delete(member)
    streaming.note_access_change(session.sync_session, user.id)


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise InvalidInputError(f"A role must be one of {', '.join(ROLES)}")


# --------------------------------------------------------------------------
# The group itself
# --------------------------------------------------------------------------


def group_payload(payload: Any) -> dict[str, Any]:
    """Return the properties out of a write body.

    An object wrapped in ``data`` is accepted as well as a bare one, so that
    what ``GET /groups/<id>`` returns can be sent straight back.
    """
    if not isinstance(payload, dict):
        raise InvalidInputError("Uploaded data must be a JSON object")
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]

    # Reported by the server and not settable: writing them would be a client
    # renumbering a library or moving its version counter. Dropped rather than
    # refused, so that a round trip of what GET returned is accepted.
    payload = {name: value for name, value in payload.items() if name not in ("id", "version")}

    unknown = set(payload) - set(_PROPERTIES) - {"owner"}
    if unknown:
        raise InvalidInputError(f"Invalid property '{sorted(unknown)[0]}'")
    return payload


def _validated(payload: dict[str, Any], *, require_name: bool) -> dict[str, str]:
    """Return the properties as strings, refusing anything out of range."""
    values: dict[str, str] = {}

    for name, allowed in _PROPERTIES.items():
        if name not in payload:
            continue
        value = payload[name]
        if not isinstance(value, str):
            raise InvalidInputError(f"'{name}' must be a string")
        if allowed is not None and value not in allowed:
            raise InvalidInputError(f"'{name}' must be one of {', '.join(allowed)}")
        values[name] = value

    if "name" in values:
        values["name"] = values["name"].strip()
        if not values["name"]:
            raise InvalidInputError("A group name is required")
        if len(values["name"]) > MAX_NAME:
            raise InvalidInputError(f"A group name may be at most {MAX_NAME} characters")
    elif require_name:
        raise InvalidInputError("A group name is required")

    return values


def _is_public(group: Group) -> bool:
    """Return whether the library behind ``group`` is readable without a key.

    Both halves have to say so. A public group whose library reading is
    restricted to members is public as a *page*, not as a library, and it is
    the library that this server serves.
    """
    return group.type in ("PublicOpen", "PublicClosed") and group.library_reading == "all"


async def _next_group_id(session: AsyncSession) -> int:
    highest = await session.scalar(
        select(func.max(Library.owner_id)).where(Library.type == LibraryType.GROUP)
    )
    return (highest or 0) + 1


async def create_group(
    session: AsyncSession,
    *,
    owner: User,
    payload: dict[str, Any],
    group_id: int | None = None,
) -> tuple[Library, Group]:
    """Create a group owned by ``owner``, who becomes its first administrator.

    The caller commits. Nothing here does, so a route can take the library lock
    and write the group in one transaction.
    """
    values = _validated(payload, require_name=True)
    if "owner" in payload and payload["owner"] != owner.id:
        # The credential decides who owns what it creates. Accepting an id here
        # would let any key make a group in somebody else's name.
        raise InvalidInputError("A group is owned by the account that creates it")

    library = Library(
        type=LibraryType.GROUP,
        owner_id=group_id if group_id is not None else await _next_group_id(session),
        name=values["name"],
        version=0,
    )
    session.add(library)
    await session.flush()

    group = Group(library_id=library.id, owner_id=owner.id, **_columns(values))
    session.add(group)
    library.public = _is_public(group)
    session.add(GroupMember(library_id=library.id, user_id=owner.id, role="admin"))
    await session.flush()

    streaming.note_access_change(session.sync_session, owner.id)
    return library, group


def _columns(values: dict[str, str]) -> dict[str, str]:
    return {_COLUMNS[name]: value for name, value in values.items()}


async def update_group(
    session: AsyncSession,
    library: Library,
    group: Group,
    payload: dict[str, Any],
    *,
    actor: User,
    replace: bool,
) -> Group:
    """Apply ``payload`` to ``group``.

    ``replace`` is the difference between ``PUT`` and ``PATCH``, and it means
    here what it means for an item: a replacing write resets what it leaves
    out. A group that had been made public and is then ``PUT`` without a
    ``type`` becomes private again, which is the safe direction for the one
    property that decides who can read it.

    A new ``owner`` is handled here rather than by a route of its own, because
    that is where upstream's shape puts it: the property is part of the group.
    Only the current owner may set it, and only to somebody already inside the
    group -- handing a library to a stranger is not a thing to do by typo.
    """
    values = _validated(payload, require_name=replace)
    if replace:
        values = {**_DEFAULTS, **values}

    if "owner" in payload and payload["owner"] != group.owner_id:
        await require_owner(session, library, actor.id)
        await _transfer(session, library, group, payload["owner"])

    for column, value in _columns(values).items():
        setattr(group, column, value)

    if "name" in values:
        # The library carries the name as well: it is what the `library` block
        # of every object in the group reports, and a rename that moved only
        # one of them would show two names for one group.
        library.name = values["name"]

    library.public = _is_public(group)
    return group


async def _transfer(
    session: AsyncSession, library: Library, group: Group, new_owner_id: Any
) -> None:
    if not isinstance(new_owner_id, int):
        raise InvalidInputError("'owner' must be a user id")

    successor = await session.get(User, new_owner_id)
    if successor is None:
        raise NotFoundError("No such user")

    member = await membership(session, library, successor.id)
    if member is None:
        raise InvalidInputError("A group can only be handed to one of its members")

    member.role = "admin"
    group.owner_id = successor.id


async def delete_group(session: AsyncSession, library: Library) -> None:
    """Delete a group library and everything in it.

    Everything: the items, their files' bookkeeping, the tags, the settings,
    the record of what was deleted, the invitations that were never answered,
    the per-key access somebody had been granted, and the activity nobody has
    been told about yet. A row left pointing at a library that no longer exists
    is a foreign key that fails on the next backend that checks.

    Undelivered activity goes with it rather than being flushed first. A digest
    is an invitation to go and look, and there would be nothing to look at.

    The stored attachment bytes are not touched. They are shared between
    libraries by digest, so removing them here would take files out from under
    another library that had uploaded the same ones.
    """
    from altero.services.transfer import clear_library

    await clear_library(session, library)

    await session.execute(delete(WriteToken).where(WriteToken.library_id == library.id))
    await session.execute(delete(StorageUpload).where(StorageUpload.library_id == library.id))
    await session.execute(
        delete(ApiKeyGroupAccess).where(ApiKeyGroupAccess.library_id == library.id)
    )
    await session.execute(delete(Invitation).where(Invitation.library_id == library.id))
    await session.execute(delete(GroupActivity).where(GroupActivity.library_id == library.id))

    members = [member.user_id for _, member in await list_members(session, library)]
    await session.execute(delete(GroupMember).where(GroupMember.library_id == library.id))
    await session.execute(delete(Group).where(Group.library_id == library.id))
    await session.execute(delete(Library).where(Library.id == library.id))

    for user_id in members:
        streaming.note_access_change(session.sync_session, user_id)
