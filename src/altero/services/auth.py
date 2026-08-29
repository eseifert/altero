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

from dataclasses import dataclass, field

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError
from altero.models import (
    ApiKey,
    ApiKeyGroupAccess,
    Collection,
    Group,
    GroupMember,
    Library,
    LibraryType,
    MemberPermission,
    OAuthGrantResource,
    User,
)
from altero.services import oauthscopes, oauthserver


@dataclass(frozen=True, slots=True)
class ResourceGrant:
    """Which libraries and collections a credential was confined to.

    Present on a :class:`Credential` only when an OAuth grant was narrowed by
    the person who made it -- ``restricted`` on the row. Its absence is the
    common case and means exactly what it meant before this existed: the scopes
    decide alone.

    Both halves are stated in database ids rather than keys, because that is
    what the row holds and what :func:`access_for` compares against. The
    collection ids here are the ones *named*; the descendants they also grant
    are worked out per library in :func:`confinement_for`, which is the one
    place that reading is applied.
    """

    #: Every library this grant names. A library absent from it is refused
    #: outright, which is what makes "group 42 and no other" one comparison
    #: rather than a rule each endpoint has to remember.
    libraries: frozenset[int] = frozenset()
    #: The collections named per library. A library present in
    #: :attr:`libraries` and absent here was granted entire.
    collections: dict[int, frozenset[int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Confinement:
    """What a :class:`ResourceGrant` leaves of one particular library.

    Three states, and the difference between the first two is the whole reason
    this is a small object rather than a set: *unconfined* is the absence of a
    restriction, and there is no set of collections that says it.
    """

    #: The library is not in the grant at all. Everything under its prefix is
    #: refused, by :func:`access_for` returning an :class:`Access` that cannot
    #: read -- so no endpoint has to know about this.
    denied: bool = False
    #: The collections reachable here, already widened to include everything
    #: nested inside each. ``None`` means the whole library.
    collections: frozenset[int] | None = None


@dataclass(frozen=True, slots=True)
class Credential:
    """What a request proved about itself, whichever way it proved it.

    An API key and an OAuth access token are two ways of saying the same six
    things, and this is those six things. Introducing it is what lets
    :func:`authenticate` answer with one type: the alternative -- handing back
    an :class:`~altero.models.ApiKey` that was never a row -- puts a transient
    instance of a mapped class on the request path, where any accidental
    ``session.add`` writes a credential into ``api_keys``.

    The flags are deliberately the ones the key already carried, because a token
    that cannot express access a key could not is a token
    :func:`access_for` needs no new rules for. The four ceilings it applies to a
    key -- the key's grants, group membership, the group's policy, the member's
    own permission -- apply to a token unchanged.
    """

    user_id: int
    library_read: bool = False
    library_write: bool = False
    notes_read: bool = False
    files_read: bool = False
    all_groups_read: bool = False
    all_groups_write: bool = False
    #: The ``api_keys`` row this came from, or ``None`` for an OAuth token.
    #: Two things ask: the per-group override, which only a key can carry, and
    #: the last-used bookkeeping, which only a key has a column for.
    key_id: int | None = None
    #: The scopes an OAuth token was issued with, for ``/oauth/userinfo`` to
    #: decide which claims it may answer with. Empty for an API key.
    scopes: str = ""
    #: Where this credential may reach, when its grant was narrowed to
    #: particular libraries or collections. ``None`` -- every API key, and every
    #: OAuth grant whose owner did not narrow it -- means the scopes decide
    #: alone. See :class:`ResourceGrant`.
    resources: ResourceGrant | None = None

    @classmethod
    def from_api_key(cls, api_key: ApiKey) -> Credential:
        """Return the credential ``api_key`` amounts to."""
        return cls(
            user_id=api_key.user_id,
            library_read=api_key.library_read,
            library_write=api_key.library_write,
            notes_read=api_key.notes_read,
            files_read=api_key.files_read,
            all_groups_read=api_key.all_groups_read,
            all_groups_write=api_key.all_groups_write,
            key_id=api_key.id,
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
    #: Whether the notes in this library may be read. A narrowing of
    #: :attr:`read` and never a way in of its own: a credential that may not
    #: read the library may not read its notes either. Defaults to ``True``
    #: because only a credential can withhold it -- a signed-in person has no
    #: key to state it on, which is why :func:`user_access` leaves it alone.
    notes: bool = True
    #: Whether the bytes behind this library's attachments may be read. The
    #: same narrowing, for files.
    files: bool = True
    #: Which :class:`~altero.models.MemberPermission` applied. ``inherit``
    #: outside a group library, and for an administrator of one.
    permission: str = MemberPermission.INHERIT.value
    #: Whose access this is, or ``None`` for an anonymous read. What ``own``
    #: compares an object's author against.
    user_id: int | None = None
    #: The collections this credential is confined to, already widened to
    #: include everything nested inside each, or ``None`` for the whole
    #: library. Set only by a resource-scoped OAuth grant --
    #: :class:`ResourceGrant` -- and ``None`` everywhere else, which is what
    #: keeps an API key, a cookie and an anonymous read behaving as before.
    #:
    #: The read services take this :class:`Access` as their ``permit`` and turn
    #: it into one predicate, so a listing, a lookup by key, a count, a search,
    #: an export and a tag count are all confined by the same clause rather than
    #: by a rule each of them remembers.
    collections: frozenset[int] | None = None

    @property
    def confined(self) -> bool:
        """Whether this credential reaches only part of the library.

        What the write paths ask before touching anything the library shares.
        """
        return self.collections is not None

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

        A credential confined to some collections may not either, and that is a
        decision rather than a consequence: none of this structure is *in* a
        collection. A saved search reaches wherever its conditions reach, a
        setting is the library's, and renaming a tag rewrites every item
        carrying it -- including the ones the confinement was drawn to exclude.
        Confining those soundly would mean inventing a per-collection meaning
        for objects that have none, so a resource-scoped grant writes items and
        leaves the library's shape alone. ``docs/compatibility.md`` records it.
        """
        return self.write and self.permission != MemberPermission.OWN and not self.confined

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
            if self.write and self.confined:
                raise ForbiddenError(_confinement_refusal())
            raise ForbiddenError(_refusal(self.permission, changing=True))

    def require_remove_structure(self) -> None:
        """Raise unless :meth:`may_remove_structure` allows it."""
        if not self.may_remove_structure():
            if self.write and self.confined:
                raise ForbiddenError(_confinement_refusal())
            raise ForbiddenError(_refusal(self.permission, changing=False))


def _confinement_refusal() -> str:
    """What a confined credential is told when it reaches the library's shape.

    Said in words for the reason :func:`_refusal` is: a sync client has no
    vocabulary for a resource-scoped grant and shows whatever comes back.
    """
    return (
        "This application was given access to particular collections, "
        "which does not include changing the library's collections, "
        "saved searches, settings or tags"
    )


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


async def authenticate(session: AsyncSession, credential: str | None) -> Credential | None:
    """Return what ``credential`` proves, whether it is a key or an OAuth token.

    Returns ``None`` when no credential was supplied. An unrecognised credential
    is an error rather than anonymous access, so that a typo in a key is not
    silently downgraded to a public-library request.

    An OAuth access token is recognised by its prefix and looked up first, which
    costs the API key path nothing: a key never carries that prefix, so the
    common case still makes exactly one query. What a token grants is decided by
    its scopes in :mod:`altero.services.oauthscopes`, and by nothing else -- a
    scope that says it reads a library reads a library, and one that says it
    establishes identity establishes identity and reaches no item.

    A credential belonging to a suspended account is refused whichever kind it
    is, which is the half of a suspension that matters: one enforced in the
    browser alone would leave every sync client of that account working exactly
    as before. For a key the owner is fetched in the same statement, so this
    costs no extra query on the path every request takes -- see
    ``tests/test_query_counts.py``.
    """
    if not credential:
        return None

    if credential.startswith(oauthserver.ACCESS_PREFIX):
        return await _authenticate_token(session, credential)

    row = (
        await session.execute(
            select(ApiKey, User.disabled_at)
            .join(User, User.id == ApiKey.user_id)
            .where(ApiKey.key == credential)
        )
    ).first()
    if row is None:
        raise ForbiddenError("Invalid key")

    api_key, disabled_at = row
    if disabled_at is not None:
        raise ForbiddenError("This account has been suspended")
    return Credential.from_api_key(api_key)


async def _authenticate_token(session: AsyncSession, credential: str) -> Credential:
    """Return what an OAuth access token proves."""
    identity = await oauthserver.resolve_access_token(session, credential)
    if identity is None:
        raise ForbiddenError("Invalid key")

    owner = await session.get(User, identity.user_id)
    if owner is None:
        raise ForbiddenError("Invalid key")
    if owner.disabled_at is not None:
        raise ForbiddenError("This account has been suspended")

    granted = oauthscopes.capabilities(identity.scopes)
    # Read off the grant rather than the token, which is what makes a refreshed
    # token the same authorization: a restriction that lived on the access token
    # would be one an application could wait out by refreshing.
    resources = (
        await resource_grant_for(session, identity.grant_id) if identity.restricted else None
    )
    return Credential(
        user_id=identity.user_id,
        library_read=granted.library_read,
        library_write=granted.library_write,
        notes_read=granted.notes_read,
        files_read=granted.files_read,
        all_groups_read=granted.all_groups_read,
        all_groups_write=granted.all_groups_write,
        key_id=None,
        scopes=identity.scopes,
        resources=resources,
    )


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
    api_key: Credential | None,
    override: ApiKeyGroupAccess | None = None,
    membership: GroupMember | None = None,
    group: Group | None = None,
    confinement: Confinement | None = None,
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

    A fifth ceiling joined the four in :class:`ResourceGrant`: where an OAuth
    grant was narrowed to particular libraries or collections, ``confinement``
    says what is left of *this* library. It is applied first and it only ever
    subtracts -- a library the grant does not name is refused outright here, so
    nothing below has to remember to ask, and a library it names by collection
    keeps the collections on the answer for the read services to filter by.

    Args:
        override: The key's per-group access for this library, if any. Only
            meaningful for group libraries.
        membership: The key owner's membership of this group, if any.
        group: The group's metadata, which says who may edit it.
        confinement: What a resource-scoped grant leaves of this library, or
            ``None`` when the credential was not narrowed. See
            :func:`confinement_for`.
    """
    if confinement is not None and confinement.denied:
        # A library the grant does not name. Refused before anything else is
        # looked at, and refused the same way an unauthenticated caller is
        # refused a private library, so a restricted token cannot use the
        # difference between "forbidden" and "not found" to map an account's
        # groups.
        return Access(
            read=False,
            write=False,
            notes=False,
            files=False,
            user_id=api_key.user_id if api_key is not None else None,
        )

    if api_key is None:
        # Nothing is being withheld from an anonymous reader that is not already
        # withheld by `public`, except the files: upstream's privacy settings
        # have no key for them at all, so `canAccess(files)` falls through to
        # its default and refuses.
        return Access(read=library.public, write=False, notes=library.public, files=False)

    if library.type is LibraryType.USER:
        # A key only ever grants write access to its own owner's library. Another
        # user's library is reachable only if it is public, and then read-only.
        if library.owner_id != api_key.user_id:
            return Access(
                read=library.public,
                write=False,
                notes=library.public,
                files=False,
                user_id=api_key.user_id,
                collections=confinement.collections if confinement is not None else None,
            )
        return Access(
            read=api_key.library_read,
            write=api_key.library_read and api_key.library_write,
            notes=_may_read_notes(library, api_key, api_key.library_read),
            files=api_key.library_read and api_key.files_read,
            user_id=api_key.user_id,
            collections=confinement.collections if confinement is not None else None,
        )

    if membership is None:
        # A stranger to the group. A public one is still readable, because that
        # is what public means, and still not writable -- and its files stay
        # shut, which is upstream's "only members have file access".
        return Access(
            read=library.public,
            write=False,
            notes=library.public,
            files=False,
            user_id=api_key.user_id,
            collections=confinement.collections if confinement is not None else None,
        )

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
        notes=_may_read_notes(library, api_key, read or library.public),
        # Membership is established by now, which is the other half of the
        # rule: a public group's files are its members' and no one else's.
        files=read and api_key.files_read,
        permission=permission,
        user_id=api_key.user_id,
        collections=confinement.collections if confinement is not None else None,
    )


def _may_read_notes(library: Library, api_key: Credential, read: bool) -> bool:
    """Whether ``api_key`` may read the notes in a library it may read.

    The ``or library.public`` is upstream's privacy fallback, and it is there so
    that a credential can never see less of a library than a stranger with no
    credential at all: what has been published is published, and withholding it
    from the account that published it would be theatre rather than a
    permission.
    """
    return read and (api_key.notes_read or library.public)


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
    api_key: Credential | None,
) -> ApiKeyGroupAccess | None:
    """Return the key's per-group access for ``library``, if one is recorded.

    Only an API key can carry one. An OAuth token has no row to hang a
    per-group override off, so it falls through to its ``groups.*`` scopes --
    which is the correct answer rather than an omission: a token's group access
    is what its scopes say, once every ceiling in :func:`access_for` has been
    applied to it.
    """
    if api_key is None or api_key.key_id is None or library.type is not LibraryType.GROUP:
        return None

    return await session.scalar(
        select(ApiKeyGroupAccess).where(
            ApiKeyGroupAccess.api_key_id == api_key.key_id,
            ApiKeyGroupAccess.library_id == library.id,
        )
    )


async def get_group_context(
    session: AsyncSession,
    library: Library,
    api_key: Credential | None,
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


async def confinement_for(
    session: AsyncSession,
    library: Library,
    api_key: Credential | None,
) -> Confinement | None:
    """Return what a resource-scoped grant leaves of ``library``.

    ``None`` when the credential carries no restriction, which is every API
    key, every cookie session and every OAuth grant whose owner did not narrow
    it -- and is why this costs an unrestricted request no query at all.

    A restricted grant that names ``library`` by collection has those
    collections widened here to include everything nested inside them. That
    widening is a decision and it is the one the rest of altero already makes:
    a shared collection means the branch, and so does the desktop client's
    "Show Items from Subcollections". Naming a collection and meaning only its
    direct contents would leave somebody who files a paper into a subcollection
    quietly withdrawing it from an application they granted the parent to.
    """
    if api_key is None or api_key.resources is None:
        return None

    grant = api_key.resources
    if library.id not in grant.libraries:
        return Confinement(denied=True)

    named = grant.collections.get(library.id)
    if named is None:
        return Confinement()

    return Confinement(collections=await _with_descendants(session, library, named))


async def _with_descendants(
    session: AsyncSession, library: Library, named: frozenset[int]
) -> frozenset[int]:
    """Return ``named`` together with every collection nested inside any of them.

    Walked a level at a time rather than with a recursive CTE, for the reason
    :func:`altero.services.collections.subtree` is -- SQLite and PostgreSQL
    spell one differently enough to be worth avoiding for a tree a handful of
    levels deep. The walk is bounded by ``found``, so a cycle that somehow
    reached the database cannot spin here.

    The library is restated in the query. A collection id that belongs to
    another library cannot widen this answer even if a grant somehow named one,
    which matters because the ids come from a row rather than from a request.
    """
    found = set(
        await session.scalars(
            select(Collection.id).where(
                Collection.library_id == library.id, Collection.id.in_(named)
            )
        )
    )
    frontier = list(found)

    while frontier:
        children = list(
            await session.scalars(
                select(Collection.id).where(
                    Collection.library_id == library.id, Collection.parent_id.in_(frontier)
                )
            )
        )
        frontier = [child for child in children if child not in found]
        found.update(frontier)

    return frozenset(found)


async def get_access(
    session: AsyncSession,
    library: Library,
    api_key: Credential | None,
) -> Access:
    """Return the access ``api_key`` has to ``library``, fetching what it needs."""
    confinement = await confinement_for(session, library, api_key)
    if confinement is not None and confinement.denied:
        # Nothing else can widen a library the grant does not name, and asking
        # would cost two queries on a request that is already refused.
        return access_for(library, api_key, confinement=confinement)

    override = await get_group_override(session, library, api_key)
    membership, group = await get_group_context(session, library, api_key)
    return access_for(library, api_key, override, membership, group, confinement)


async def resource_grant_for(session: AsyncSession, grant_id: int) -> ResourceGrant | None:
    """Return the resources ``grant_id`` was narrowed to, or ``None`` if it was not.

    Read off :class:`~altero.models.OAuthGrantResource` on every request a token
    makes, which is one query and only for a restricted grant: the caller has
    already read ``restricted`` off the grant row it had in hand.
    """
    rows = list(
        await session.execute(
            select(OAuthGrantResource.library_id, OAuthGrantResource.collection_id).where(
                OAuthGrantResource.grant_id == grant_id
            )
        )
    )

    libraries: set[int] = set()
    collections: dict[int, set[int]] = {}
    whole: set[int] = set()
    for library_id, collection_id in rows:
        libraries.add(library_id)
        if collection_id is None:
            whole.add(library_id)
        else:
            collections.setdefault(library_id, set()).add(collection_id)

    # A library named both entire and by collection is named entire: the wider
    # row is the one its owner ticked, and narrowing it by the other would make
    # the order the rows were written in decide what the grant means.
    return ResourceGrant(
        libraries=frozenset(libraries),
        collections={
            library_id: frozenset(ids)
            for library_id, ids in collections.items()
            if library_id not in whole
        },
    )


async def require_read(
    session: AsyncSession,
    library: Library,
    api_key: Credential | None,
) -> None:
    """Raise :class:`ForbiddenError` unless ``api_key`` may read ``library``."""
    if not (await get_access(session, library, api_key)).read:
        raise ForbiddenError("Forbidden")


async def require_write(
    session: AsyncSession,
    library: Library,
    api_key: Credential | None,
) -> None:
    """Raise :class:`ForbiddenError` unless ``api_key`` may write to ``library``."""
    if not (await get_access(session, library, api_key)).write:
        raise ForbiddenError("Forbidden")


async def require_file_write(
    session: AsyncSession,
    library: Library,
    api_key: Credential | None,
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
