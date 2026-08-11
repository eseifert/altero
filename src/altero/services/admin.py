"""Provisioning of users, libraries, API keys and groups.

These back the command line rather than any endpoint: the Web API has no way to
create an account or issue a credential, so without them a deployment could only
be set up by writing rows by hand.
"""

from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.keys import generate_api_key
from altero.models import (
    ApiKey,
    ApiKeyGroupAccess,
    EmailVerification,
    Group,
    GroupMember,
    Invitation,
    Library,
    LibraryType,
    LoginSession,
    Notification,
    StorageUpload,
    TotpCredential,
    User,
    WebSession,
    WriteToken,
)
from altero.services import groups, streaming, websessions
from altero.services.transfer import clear_library


async def _next_user_id(session: AsyncSession) -> int:
    """Return an unused user id.

    Ids are assigned here rather than by the database because they appear in
    URLs and must survive a restore into an empty table.
    """
    highest = await session.scalar(select(func.max(User.id)))
    return (highest or 0) + 1


async def _no_users_yet(session: AsyncSession) -> bool:
    """Return whether this instance has no accounts at all."""
    return (await session.scalar(select(func.count()).select_from(User))) == 0


async def count_administrators(session: AsyncSession) -> int:
    """Return how many accounts administer the instance."""
    return (
        await session.scalar(
            select(func.count()).select_from(User).where(User.administrator.is_(True))
        )
    ) or 0


async def set_administrator(session: AsyncSession, user: User, *, administrator: bool) -> User:
    """Say whether ``user`` administers the instance.

    Refuses to take the last one away. An instance with no administrator can
    only be given one from a shell on the server, which is the thing this whole
    layer exists to stop being necessary -- so it must not be reachable by one
    careless click, and least of all by the operator clicking on themselves.
    """
    if user.administrator and not administrator and await count_administrators(session) <= 1:
        raise InvalidInputError(
            "This is the last administrator of this instance; promote somebody "
            "else before standing down"
        )

    user.administrator = administrator
    await session.commit()
    return user


async def set_disabled(session: AsyncSession, user: User, *, disabled: bool) -> User:
    """Take ``user`` out of service, or put them back.

    Access stops and the data stays: their libraries, their memberships and
    what they published are untouched, and reinstating them is clearing this.
    That is the difference between somebody leaving and somebody's account
    being deleted, and the deprovisioning half of what an institution needs
    when a student graduates.

    Both credentials are refused, not one. A flag the browser honoured alone
    would leave every sync client of a suspended account working exactly as
    before, which is not a suspension at all -- see
    :func:`altero.services.auth.authenticate` and
    :func:`altero.services.websessions.lookup`.

    Their sessions go, because a browser already signed in would otherwise keep
    working until its cookie expired.
    """
    if disabled and user.administrator and await count_administrators(session) <= 1:
        raise InvalidInputError(
            "This is the last administrator of this instance; suspending them "
            "would leave nobody able to put them back"
        )

    user.disabled_at = datetime.now(UTC).replace(tzinfo=None) if disabled else None
    await session.commit()

    if disabled:
        await websessions.revoke_all(session, user)
    return user


async def revoke_credentials(session: AsyncSession, user: User) -> tuple[int, int]:
    """Drop every API key and every signed-in browser. Returns how many of each.

    What you do when a laptop is lost rather than when somebody leaves: the
    account goes on working, and everything holding a credential for it has to
    ask again.
    """
    keys = list(await session.scalars(select(ApiKey).where(ApiKey.user_id == user.id)))
    for key in keys:
        await session.delete(key)

    sessions = list(await session.scalars(select(WebSession).where(WebSession.user_id == user.id)))
    for record in sessions:
        await session.delete(record)

    await session.commit()
    return len(keys), len(sessions)


async def delete_user(session: AsyncSession, user: User) -> None:
    """Remove an account, its personal library and everything in it.

    Refused while the account owns a group, and the groups are named rather
    than guessed at: handing one on is its own operation with its own screen,
    and picking an heir here would be this server deciding who inherits
    somebody else's shared library.

    The library goes through the same :func:`~altero.services.transfer.
    clear_library` a group deletion uses, so there is one answer to "what is in
    a library" and this is not a second one. Attachment bytes stay: they are
    shared by digest, and removing them here would take files out from under
    another library that had uploaded the same ones.
    """
    if user.administrator and await count_administrators(session) <= 1:
        raise InvalidInputError(
            "This is the last administrator of this instance; promote somebody "
            "else before deleting the account"
        )

    owned = list(
        await session.scalars(
            select(Group.name)
            .join(Library, Library.id == Group.library_id)
            .where(Group.owner_id == user.id)
        )
    )
    if owned:
        raise InvalidInputError(
            f"{user.username} owns {', '.join(sorted(owned))}. Hand each group on "
            "to somebody else before deleting the account, or delete the group."
        )

    library = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == user.id)
    )
    if library is not None:
        await clear_library(session, library)
        await session.execute(delete(WriteToken).where(WriteToken.library_id == library.id))
        await session.execute(delete(StorageUpload).where(StorageUpload.library_id == library.id))
        await session.execute(
            delete(ApiKeyGroupAccess).where(ApiKeyGroupAccess.library_id == library.id)
        )
        await session.execute(delete(Invitation).where(Invitation.library_id == library.id))

    keys = select(ApiKey.id).where(ApiKey.user_id == user.id)
    await session.execute(delete(ApiKeyGroupAccess).where(ApiKeyGroupAccess.api_key_id.in_(keys)))
    # A client login points at a key, and the key is about to go.
    await session.execute(
        update(LoginSession).where(LoginSession.api_key_id.in_(keys)).values(api_key_id=None)
    )
    await session.execute(delete(ApiKey).where(ApiKey.user_id == user.id))

    await session.execute(delete(WebSession).where(WebSession.user_id == user.id))
    await session.execute(delete(TotpCredential).where(TotpCredential.user_id == user.id))
    await session.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    await session.execute(delete(Notification).where(Notification.user_id == user.id))
    # Invitations they sent as well as ones addressed to them: `invited_by`
    # points here and cannot be left dangling.
    await session.execute(
        delete(Invitation).where(
            or_(Invitation.invited_by == user.id, Invitation.user_id == user.id)
        )
    )
    memberships = list(
        await session.scalars(select(GroupMember).where(GroupMember.user_id == user.id))
    )
    await session.execute(delete(GroupMember).where(GroupMember.user_id == user.id))

    if library is not None:
        await session.execute(delete(Library).where(Library.id == library.id))
    await session.delete(user)
    await session.commit()

    # Whoever shared a group with them sees a membership change; the account
    # itself is gone and hears nothing.
    for member in memberships:
        streaming.note_access_change(session.sync_session, member.user_id)


async def get_user_by_name(session: AsyncSession, username: str) -> User:
    """Return the named user."""
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        raise NotFoundError(f"No user named '{username}'")
    return user


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    display_name: str = "",
    user_id: int | None = None,
) -> User:
    """Create a user and the personal library that belongs to them."""
    if not username:
        raise InvalidInputError("A username is required")
    if "@" in username:
        # Sign-in reads an identifier containing "@" as an address, so a
        # username holding one would be unreachable at best and would collide
        # with somebody's real address at worst.
        raise InvalidInputError("A username may not contain '@'")

    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise InvalidInputError(f"A user named '{username}' already exists")

    user = User(
        id=user_id if user_id is not None else await _next_user_id(session),
        username=username,
        display_name=display_name,
        # The account that claims an instance administers it. Decided here
        # rather than in each caller, so that `altero user add` on a fresh
        # database and the browser's registration form agree: an instance
        # whose first account was made the other way would have an operator
        # view nobody can open.
        administrator=await _no_users_yet(session),
    )
    session.add(user)
    await session.flush()

    session.add(
        Library(
            type=LibraryType.USER,
            owner_id=user.id,
            name=display_name or username,
            version=0,
        )
    )
    await session.commit()
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list(await session.scalars(select(User).order_by(User.id)))


async def create_api_key(
    session: AsyncSession,
    *,
    username: str,
    name: str,
    read: bool = True,
    write: bool = True,
    notes: bool = True,
    files: bool = True,
    all_groups_read: bool = False,
    all_groups_write: bool = False,
) -> ApiKey:
    """Issue an API key for a user and return it.

    The key itself is only available here; nothing later can recover it, so the
    caller is responsible for showing it once.
    """
    user = await get_user_by_name(session, username)

    api_key = ApiKey(
        key=generate_api_key(),
        user_id=user.id,
        name=name,
        library_read=read,
        library_write=write,
        notes_read=notes,
        files_read=files,
        all_groups_read=all_groups_read,
        all_groups_write=all_groups_write,
    )
    session.add(api_key)
    await session.commit()
    return api_key


async def list_api_keys(session: AsyncSession) -> list[ApiKey]:
    return list(await session.scalars(select(ApiKey).order_by(ApiKey.id)))


async def revoke_api_key(session: AsyncSession, key: str) -> None:
    """Delete an API key so that it stops working immediately."""
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key == key))
    if api_key is None:
        raise NotFoundError("No such key")
    await session.delete(api_key)
    await session.commit()


async def create_group(
    session: AsyncSession,
    *,
    name: str,
    owner_username: str,
    group_id: int | None = None,
    public: bool = False,
) -> Library:
    """Create a group library owned by a user, who becomes its first admin.

    Through :mod:`altero.services.groups`, which is also what the API's
    ``POST /groups`` goes through, so the command line and the endpoint cannot
    disagree about what a new group is.
    """
    owner = await get_user_by_name(session, owner_username)
    payload: dict[str, str] = {"name": name}
    if public:
        # Public as a page and public as a library are separate settings, and
        # `--public` on the command line means both -- there being no third
        # thing it could reasonably mean.
        payload |= {"type": "PublicOpen", "libraryReading": "all"}

    library, _ = await groups.create_group(session, owner=owner, payload=payload, group_id=group_id)
    await session.commit()
    return library


async def add_group_member(
    session: AsyncSession,
    library: Library,
    *,
    username: str,
    role: str = "member",
    permission: str = "inherit",
) -> GroupMember:
    """Add a user to a group library."""
    user = await get_user_by_name(session, username)
    member = await groups.add_member(session, library, user, role, permission)
    await session.commit()
    return member


async def set_group_member_role(
    session: AsyncSession, library: Library, *, username: str, role: str
) -> GroupMember:
    """Change whether a member helps run a group library."""
    user = await get_user_by_name(session, username)
    member = await groups.set_role(session, library, user, role)
    await session.commit()
    return member


async def set_group_member_permission(
    session: AsyncSession, library: Library, *, username: str, permission: str
) -> GroupMember:
    """Change how far a member of a group library may go."""
    user = await get_user_by_name(session, username)
    member = await groups.set_permission(session, library, user, permission)
    await session.commit()
    return member


async def remove_group_member(session: AsyncSession, library: Library, *, username: str) -> None:
    """Take a user out of a group library."""
    user = await get_user_by_name(session, username)
    await groups.remove_member(session, library, user)
    await session.commit()


async def delete_group(session: AsyncSession, library: Library) -> None:
    """Delete a group library and everything in it."""
    await groups.delete_group(session, library)
    await session.commit()


async def list_group_members(session: AsyncSession, library: Library) -> list[GroupMember]:
    return list(
        await session.scalars(
            select(GroupMember)
            .where(GroupMember.library_id == library.id)
            .order_by(GroupMember.user_id)
        )
    )


async def list_libraries(session: AsyncSession) -> list[Library]:
    return list(await session.scalars(select(Library).order_by(Library.id)))


async def set_library_version(
    session: AsyncSession,
    *,
    library_type: LibraryType,
    owner_id: int,
    version: int,
) -> Library:
    """Raise a library's version counter to ``version``.

    A library recreated from an empty database starts counting at zero again,
    while clients that synced against the original still hold the version they
    last saw. The desktop application refuses to move its stored version
    backwards -- during an ordinary sync and during "restore to server" alike --
    so it can neither upload nor be reset out of the state. Lifting the counter
    back over what the clients remember is the only way to reach them again.

    Which is also why the version may only ever go up: lowering one is how a
    working deployment locks itself out.
    """
    if version < 0:
        raise InvalidInputError("A library version cannot be negative")

    library = await session.scalar(
        select(Library).where(Library.type == library_type, Library.owner_id == owner_id)
    )
    if library is None:
        raise NotFoundError(f"No {library_type.value} library with id {owner_id}")

    if version < library.version:
        raise InvalidInputError(
            f"A library version cannot be lowered (it is {library.version}); "
            "clients that have seen it would stop syncing"
        )

    library.version = version
    await session.commit()
    return library
