"""Authentication, library lookup and access control.

This module deliberately knows nothing about HTTP: callers pass a credential
string that they extracted however they like, and get back domain objects or a
domain error.

Permission resolution is split in two. :func:`access_for` is a pure function of
values already in hand, so the rules can be read and tested on their own;
:func:`get_access` is the async wrapper that fetches the per-group override it
needs. Nothing here relies on lazy relationship loading, which would otherwise
fail whenever a key reached the check without having been loaded by a query.
"""

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError
from altero.models import (
    ApiKey,
    ApiKeyGroupAccess,
    Group,
    GroupMember,
    Library,
    LibraryType,
    MemberPermission,
    User,
)


@dataclass(frozen=True, slots=True)
class Access:
    """The access a credential has to one library.

    ``read`` and ``write`` are the whole answer for a personal library and for
    every group membership that carries no permission of its own, which is all
    of them by default. :attr:`permission` is the fourth ceiling
    :class:`~altero.models.MemberPermission` describes, and it is the reason
    this is a small object with questions on it rather than two booleans: "may
    this credential write here" stops being answerable without knowing *what*
    is being written and *who put it there*.

    A read-only member needs none of that: :func:`access_for` has already
    turned their permission into ``write=False``, so every path that could
    refuse them already does. The two that need asking are ``add``, which may
    change anything and remove nothing, and ``own``, which may touch only what
    it added.
    """

    read: bool
    write: bool
    #: Which :class:`~altero.models.MemberPermission` applied. ``inherit``
    #: outside a group library, and for an administrator of one.
    permission: str = MemberPermission.INHERIT.value
    #: Whose access this is, or ``None`` for an anonymous read. What ``own``
    #: compares an object's author against.
    user_id: int | None = None

    def may_change(self, created_by: int | None) -> bool:
        """Whether this credential may change an object ``created_by`` added.

        ``created_by`` is ``None`` for anything with no recorded author -- an
        object written before altero recorded one, or by a path that had no
        account to name. An ``own`` member may not touch it: an unowned object
        is not theirs, and the safe direction for a restriction is to hold.
        """
        if not self.write:
            return False
        if self.permission == MemberPermission.OWN:
            return created_by is not None and created_by == self.user_id
        return True

    def may_remove(self, created_by: int | None) -> bool:
        """Whether this credential may take that object out of the library.

        Trashing counts. It is how the desktop client deletes, and a member who
        may not delete but may trash could still empty a library in one gesture
        -- which is the thing this was asked for after.
        """
        if self.permission == MemberPermission.ADD:
            return False
        return self.may_change(created_by)

    def may_change_structure(self) -> bool:
        """Whether this credential may write the library's shared structure.

        Its collections, its saved searches and its settings, none of which
        records who made it. ``own`` therefore cannot tell one member's from
        another's and treats all of it as somebody else's; filing an item into
        a collection is a write to the *item* and stays allowed.
        """
        return self.write and self.permission != MemberPermission.OWN

    def may_remove_structure(self) -> bool:
        """Whether this credential may delete a collection, search or setting."""
        return self.may_change_structure() and self.permission != MemberPermission.ADD

    def require_change(self, created_by: int | None) -> None:
        """Raise unless :meth:`may_change` allows it."""
        if not self.may_change(created_by):
            raise ForbiddenError(_refusal(self.permission, changing=True))

    def require_remove(self, created_by: int | None) -> None:
        """Raise unless :meth:`may_remove` allows it."""
        if not self.may_remove(created_by):
            raise ForbiddenError(_refusal(self.permission, changing=False))

    def require_change_structure(self) -> None:
        """Raise unless :meth:`may_change_structure` allows it."""
        if not self.may_change_structure():
            raise ForbiddenError(_refusal(self.permission, changing=True))

    def require_remove_structure(self) -> None:
        """Raise unless :meth:`may_remove_structure` allows it."""
        if not self.may_remove_structure():
            raise ForbiddenError(_refusal(self.permission, changing=False))


def _refusal(permission: str, *, changing: bool) -> str:
    """Return what a refusal should say.

    Said in words rather than as a bare "Forbidden" because the desktop client
    has no vocabulary for either of these permissions and will show whatever
    comes back as a sync error. That message is the only explanation the person
    holding the restriction is going to get.
    """
    if permission == MemberPermission.ADD:
        return "You can add to this group library but not remove from it"
    if permission == MemberPermission.OWN:
        if changing:
            return "You can only change what you added to this group library"
        return "You can only remove what you added to this group library"
    return "Forbidden"


async def authenticate(session: AsyncSession, credential: str | None) -> ApiKey | None:
    """Return the API key identified by ``credential``.

    Returns ``None`` when no credential was supplied. An unrecognised credential
    is an error rather than anonymous access, so that a typo in a key is not
    silently downgraded to a public-library request.

    A key belonging to a suspended account is refused, which is the half of a
    suspension that matters: one enforced in the browser alone would leave
    every sync client of that account working exactly as before. The owner is
    fetched in the same statement, so this costs no extra query on the path
    every request takes -- see ``tests/test_query_counts.py``.
    """
    if not credential:
        return None

    row = (
        await session.execute(
            select(ApiKey, User.disabled_at)
            .join(User, User.id == ApiKey.user_id)
            .where(ApiKey.key == credential)
        )
    ).first()
    if row is None:
        from altero.services import oauth
        token_obj = await oauth.validate_access_token(session, credential)
        if token_obj is not None:
            user = await session.scalar(select(User).where(User.id == token_obj.user_id))
            if user is None:
                raise ForbiddenError("Invalid key")
            if user.disabled_at is not None:
                raise ForbiddenError("This account has been suspended")
            scopes = token_obj.scopes.split()
            return ApiKey(
                id=0,
                key=credential,
                user_id=token_obj.user_id,
                name="OAuth Token",
                library_read="library.read" in scopes or "openid" in scopes,
                library_write="library.write" in scopes or "annotations.write" in scopes,
                notes_read="library.read" in scopes or "openid" in scopes,
                files_read="files.read" in scopes or "openid" in scopes,
                all_groups_read="library.read" in scopes or "openid" in scopes,
                all_groups_write="library.write" in scopes,
            )
        raise ForbiddenError("Invalid key")

    api_key, disabled_at = row
    if disabled_at is not None:
        raise ForbiddenError("This account has been suspended")
    return api_key


async def get_library(
    session: AsyncSession,
    library_type: LibraryType,
    owner_id: int,
) -> Library:
    """Return the library addressed by a ``/users/<id>`` or ``/groups/<id>`` prefix."""
    library = await session.scalar(
        select(Library).where(Library.type == library_type, Library.owner_id == owner_id)
    )
    if library is None:
        raise NotFoundError("Not found")
    return library


def access_for(
    library: Library,
    api_key: ApiKey | None,
    override: ApiKeyGroupAccess | None = None,
    membership: GroupMember | None = None,
    group: Group | None = None,
) -> Access:
    """Return the access ``api_key`` has to ``library``.

    A public library is readable by anyone, including unauthenticated callers.
    Write access always implies read access, so a key that may write but not read
    can do neither.

    For a group library four things have to agree, and every one of them is a
    ceiling rather than a grant: the key's group permissions, membership of the
    group, the group's own policy, and the member's own permission. A key saying
    "all groups" means every group its owner belongs to -- not every group on
    the server, which is what it used to mean here and which let anyone holding
    such a key read every private library on the instance.

    The fourth is :class:`~altero.models.MemberPermission`, and being a ceiling
    is the whole of how it composes: a member marked ``add`` in a group that
    reserves editing for its administrators has already lost ``write`` by the
    time their permission is looked at, so it cannot give them anything.

    Args:
        override: The key's per-group access for this library, if any. Only
            meaningful for group libraries.
        membership: The key owner's membership of this group, if any.
        group: The group's metadata, which says who may edit it.
    """
    if api_key is None:
        return Access(read=library.public, write=False)

    if library.type is LibraryType.USER:
        # A key only ever grants write access to its own owner's library. Another
        # user's library is reachable only if it is public, and then read-only.
        if library.owner_id != api_key.user_id:
            return Access(read=library.public, write=False, user_id=api_key.user_id)
        return Access(
            read=api_key.library_read,
            write=api_key.library_read and api_key.library_write,
            user_id=api_key.user_id,
        )

    if membership is None:
        # A stranger to the group. A public one is still readable, because that
        # is what public means, and still not writable.
        return Access(read=library.public, write=False, user_id=api_key.user_id)

    if override is not None:
        read, write = override.read, override.write
    else:
        read, write = api_key.all_groups_read, api_key.all_groups_write

    # A group may reserve editing for its administrators. Reading is decided by
    # `library.public` together with the key, which is where `libraryReading`
    # has already been resolved to.
    if group is not None and group.library_editing == "admins" and membership.role != "admin":
        write = False

    permission = member_permission(membership)
    if permission == MemberPermission.READ:
        # The one permission with a way of saying itself to a sync client, and
        # it says it here: nothing further down has to know about it, because
        # what reaches the write paths is a credential that cannot write.
        write = False

    return Access(
        read=read or library.public,
        write=read and write,
        permission=permission,
        user_id=api_key.user_id,
    )


def member_permission(membership: GroupMember) -> str:
    """Return the permission this membership carries.

    An administrator's is always ``inherit``, whatever the column says: a
    restriction somebody can lift by editing their own membership is not one.
    :func:`altero.services.groups.set_permission` refuses to store one on an
    administrator, and clearing it on promotion is what
    :func:`altero.services.groups.set_role` does; this is the third place that
    could disagree with those two, so it agrees with them by construction.
    """
    if membership.role == "admin":
        return MemberPermission.INHERIT.value
    return membership.permission


async def get_group_override(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> ApiKeyGroupAccess | None:
    """Return the key's per-group access for ``library``, if one is recorded."""
    if api_key is None or library.type is not LibraryType.GROUP:
        return None

    return await session.scalar(
        select(ApiKeyGroupAccess).where(
            ApiKeyGroupAccess.api_key_id == api_key.id,
            ApiKeyGroupAccess.library_id == library.id,
        )
    )


async def get_group_context(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> tuple[GroupMember | None, Group | None]:
    """Return the caller's membership of ``library`` and the group's policy.

    One query with an outer join rather than two, because this runs on every
    request addressed to a group library.
    """
    if api_key is None or library.type is not LibraryType.GROUP:
        return None, None

    row = (
        await session.execute(
            select(GroupMember, Group)
            .select_from(Group)
            .outerjoin(
                GroupMember,
                and_(
                    GroupMember.library_id == Group.library_id,
                    GroupMember.user_id == api_key.user_id,
                ),
            )
            .where(Group.library_id == library.id)
        )
    ).first()

    return (row[0], row[1]) if row is not None else (None, None)


async def get_access(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> Access:
    """Return the access ``api_key`` has to ``library``, fetching what it needs."""
    override = await get_group_override(session, library, api_key)
    membership, group = await get_group_context(session, library, api_key)
    return access_for(library, api_key, override, membership, group)


async def require_read(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> None:
    """Raise :class:`ForbiddenError` unless ``api_key`` may read ``library``."""
    if not (await get_access(session, library, api_key)).read:
        raise ForbiddenError("Forbidden")


async def require_write(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> None:
    """Raise :class:`ForbiddenError` unless ``api_key`` may write to ``library``."""
    if not (await get_access(session, library, api_key)).write:
        raise ForbiddenError("Forbidden")


async def require_file_write(
    session: AsyncSession,
    library: Library,
    api_key: ApiKey | None,
) -> None:
    """Raise unless ``api_key`` may put files in ``library``.

    A group carries a ``fileEditing`` policy of its own, separate from who may
    edit the library: a group can let every member add items and still keep the
    attachments -- which is where the disk goes -- to its administrators, or
    forbid them outright. A personal library has no such distinction.
    """
    await require_write(session, library, api_key)

    membership, group = await get_group_context(session, library, api_key)
    if group is None or membership is None:
        return

    if group.file_editing == "none":
        raise ForbiddenError("This group does not allow file uploads")
    if group.file_editing == "admins" and membership.role != "admin":
        raise ForbiddenError("Only an administrator of this group can upload files")


async def user_access(session: AsyncSession, library: Library, user_id: int) -> Access:
    """Return the access the person ``user_id`` has to ``library``.

    The counterpart to :func:`access_for` for a credential that is a signed-in
    person rather than an API key. A key is a ceiling on what its owner may do,
    and there is no key here to lower it, so what remains is the library: its
    owner may do anything to their own, a member does what the group's policy
    allows, and a public library is readable by anyone.

    This is not a second set of rules. It is the same three questions with the
    key's grants taken out, which is why it lives beside them rather than in
    whatever endpoint happened to need it first.
    """
    if library.type is LibraryType.USER:
        if library.owner_id == user_id:
            return Access(read=True, write=True, user_id=user_id)
        return Access(read=library.public, write=False, user_id=user_id)

    row = (
        await session.execute(
            select(GroupMember, Group)
            .select_from(Group)
            .outerjoin(
                GroupMember,
                and_(
                    GroupMember.library_id == Group.library_id,
                    GroupMember.user_id == user_id,
                ),
            )
            .where(Group.library_id == library.id)
        )
    ).first()
    membership, group = (row[0], row[1]) if row is not None else (None, None)

    if membership is None:
        # A stranger to the group. A public one is still readable, and still
        # not writable, exactly as it is for a key.
        return Access(read=library.public, write=False, user_id=user_id)

    write = not (
        group is not None and group.library_editing == "admins" and membership.role != "admin"
    )
    permission = member_permission(membership)
    if permission == MemberPermission.READ:
        write = False

    return Access(read=True, write=write, permission=permission, user_id=user_id)


async def get_user(session: AsyncSession, user_id: int) -> User:
    """Return the user with ``user_id``."""
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("Not found")
    return user


async def get_api_key_by_value(session: AsyncSession, key: str) -> ApiKey:
    """Return the API key with this key string."""
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key == key))
    if api_key is None:
        raise NotFoundError("No such key")
    return api_key


async def list_group_overrides(
    session: AsyncSession,
    api_key: ApiKey,
) -> list[ApiKeyGroupAccess]:
    """Return every per-group access recorded for ``api_key``."""
    result = await session.scalars(
        select(ApiKeyGroupAccess).where(ApiKeyGroupAccess.api_key_id == api_key.id)
    )
    return list(result)
