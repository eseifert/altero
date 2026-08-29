"""Group endpoints: reading a group, and administering one.

Reading is upstream's. Administering is not, quite. Upstream serves
``POST /groups`` and ``POST /groups/<id>/users`` behind
``$this->permissions->isSuper()``, which no API key can satisfy, with **XML**
bodies parsed by ``new SimpleXMLElement($this->body)``. It is zotero.org's
administrative back door rather than part of the API a client uses, and the
Zotero client never calls it.

altero serves the same paths with the credential the rest of the v3 API uses
and the body format the rest of the v3 API uses: an API key, and JSON in the
shape ``GET /groups/<id>`` already returns, so what was read can be sent back.
``docs/compatibility.md`` records the divergence and why inventing a superuser
credential was not the alternative.

Two rules decide who may do what. A key must be **allowed to write** to the
group, and its owner must be an **administrator** of it -- the two are separate
because putting items in a library and deciding who else may are separate
things. Handing the group on and deleting it need the owner, since both end
the group as its members know it.
"""

from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero import serializers
from altero.api.deps import ApiKeyDep, BaseUrlDep, LibraryDep, SessionDep
from altero.api.responses import library_headers, object_response
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.models import (
    Group,
    GroupMember,
    Library,
    LibraryType,
    MemberPermission,
    User,
)
from altero.query import Format
from altero.services import auth, groups, writes

router = APIRouter(tags=["groups"])


def _member_payload(user: User, member: GroupMember) -> dict[str, Any]:
    """Render one member.

    A shape of altero's own: upstream answers ``403`` here to anything an API
    key can present, so there is nothing to copy. It names the account the way
    ``/keys/<key>`` does, so the two read alike.

    ``permission`` is altero's too, and the group JSON beside it says nothing
    about anybody's -- ``libraryEditing`` there is what *the requester* may do,
    not a roster. This is the roster, and only a member of the group can read
    it.
    """
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": member.role,
        "permission": auth.member_permission(member),
    }


async def _writer(
    session: AsyncSession, library: Library, api_key: auth.Credential | None
) -> auth.Credential:
    """Return the key, requiring that it may write to this group at all.

    Separate from the admin check and made first, so that a read-only key is
    told it cannot write rather than that it is not an administrator -- which
    would be misleading for somebody who is one.
    """
    if api_key is None:
        raise ForbiddenError("Forbidden")
    if library.type is not LibraryType.GROUP:
        raise InvalidInputError("Only a group library has members")

    access = await auth.get_access(session, library, api_key)
    if not access.write:
        raise ForbiddenError("This key may not write to this group")
    # A group's metadata and its membership are the group's shape, so a
    # credential confined to some of its collections is held to the same line
    # here as it is on the library's collections and saved searches: a grant to
    # one collection is not a grant to decide who is in the group.
    access.require_change_structure()
    return api_key


async def _admin(session: AsyncSession, library: Library, api_key: auth.Credential | None) -> User:
    """Return the account administering this group through ``api_key``."""
    key = await _writer(session, library, api_key)
    await groups.require_admin(session, library, key.user_id)
    return await auth.get_user(session, key.user_id)


async def _rendered(
    session: AsyncSession,
    library: Library,
    base_url: str,
    api_key: auth.Credential | None = None,
    group: Group | None = None,
) -> dict[str, Any]:
    """Render the group as *this* requester sees it.

    ``libraryEditing`` is the one property that differs between requesters --
    :func:`altero.services.groups.editing_for` says why -- so every route that
    renders a group has to say who is asking.
    """
    group = group or await groups.get_group(session, library)
    member = (
        await groups.membership(session, library, api_key.user_id) if api_key is not None else None
    )
    return serializers.group(
        library, group, base_url, library_editing=groups.editing_for(group, member)
    )


async def _body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError:
        raise InvalidInputError("Uploaded data must be a JSON object") from None
    return groups.group_payload(payload)


@router.get("/groups/{group_id}")
async def get_group(
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> Response:
    """Return one group's metadata.

    Readable by anyone who may read the library, which for a public group is
    anyone at all. A group the caller may not read answers 404 rather than 403,
    which is what upstream's `canAccess` check does: a stranger learns nothing
    about which private groups exist.
    """
    try:
        await auth.require_read(session, library, api_key)
    except ForbiddenError:
        raise NotFoundError("Group not found") from None

    return object_response(await _rendered(session, library, base_url, api_key), library.version)


@router.get("/users/{user_id}/groups")
async def list_user_groups(
    user_id: int,
    request: Request,
    session: SessionDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> Response:
    """Return the groups a user belongs to.

    Only the user themselves may list their groups.

    ``format=versions`` answers with group id to version rather than the
    listing, because that is the first thing the client asks for every sync and
    it iterates the answer by key. Handed the JSON array instead, it reads
    array indices as group ids and the sync stops at group ``0``. The version is
    the library's, which is the one ``GET /groups/<id>`` reports, so the client
    compares like with like when deciding whether to fetch the group again.
    """
    if api_key is None or api_key.user_id != user_id:
        raise ForbiddenError("Forbidden")

    await auth.get_user(session, user_id)
    memberships = await groups.list_groups_for_user(session, user_id)

    if (resources := api_key.resources) is not None:
        # A resource-scoped grant names the group libraries it reaches, so this
        # lists those and no others. Without it an application given one group
        # would still be handed the id, name and description of every group its
        # owner belongs to -- which is the leak the grant was made to close, and
        # it would happen on the first request of every sync.
        memberships = [entry for entry in memberships if entry[0].id in resources.libraries]

    if request.query_params.get("format") == Format.VERSIONS:
        return JSONResponse(
            {str(library.owner_id): library.version for library, _, _ in memberships}
        )

    return JSONResponse(
        [
            serializers.group(
                library, group, base_url, library_editing=groups.editing_for(group, member)
            )
            for library, group, member in memberships
        ]
    )


@router.post("/groups", status_code=201)
async def create_group(
    request: Request,
    session: SessionDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> Response:
    """Create a group owned by the account the key belongs to.

    A key that may not write to its owner's own library may not create one
    either: creating a group is the account acting on its own data, and a
    read-only credential is not the account acting.
    """
    if api_key is None:
        raise ForbiddenError("Forbidden")

    personal = await auth.get_library(session, LibraryType.USER, api_key.user_id)
    access = await auth.get_access(session, personal, api_key)
    if not access.write:
        raise ForbiddenError("This key may not create groups")
    # Confined to some collections is confined: making a whole new library is
    # the widest thing this credential could be asked to do, and it is not what
    # a grant to a collection was given for.
    access.require_change_structure()

    owner = await auth.get_user(session, api_key.user_id)
    library, group = await groups.create_group(session, owner=owner, payload=await _body(request))
    await session.commit()

    return JSONResponse(
        await _rendered(session, library, base_url, api_key, group),
        status_code=201,
        headers=library_headers(library.version),
    )


@router.put("/groups/{group_id}")
async def replace_group(
    request: Request,
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> Response:
    """Replace a group's metadata. Properties left out are reset."""
    return await _write_group(request, session, library, api_key, base_url, replace=True)


@router.patch("/groups/{group_id}")
async def update_group(
    request: Request,
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> Response:
    """Change a group's metadata in place. Properties left out are untouched."""
    return await _write_group(request, session, library, api_key, base_url, replace=False)


async def _write_group(
    request: Request,
    session: AsyncSession,
    library: Library,
    api_key: auth.Credential | None,
    base_url: str,
    *,
    replace: bool,
) -> Response:
    """Apply a metadata write. Administrators only.

    The library's version moves, as it does for any other write: the group's
    name is what the ``library`` block of every object in it reports, so a
    client that has not noticed the change is showing the old one.
    """
    actor = await _admin(session, library, api_key)
    payload = await _body(request)

    library = await writes.lock_library(session, library)
    group = await groups.get_group(session, library)
    await groups.update_group(session, library, group, payload, actor=actor, replace=replace)
    version = await writes.bump_library_version(session, library)
    await session.commit()

    return object_response(await _rendered(session, library, base_url, api_key, group), version)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
) -> Response:
    """Delete a group and everything in it. The owner only.

    There is no undo and no trash: a group is a library, and the trash is
    inside a library rather than around one. The owner is the only person who
    can reach this, which is the whole of the protection.
    """
    key = await _writer(session, library, api_key)
    await groups.require_owner(session, library, key.user_id)

    await groups.delete_group(session, library)
    await session.commit()
    return Response(status_code=204)


@router.get("/groups/{group_id}/users")
async def list_group_users(
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
) -> Response:
    """List the group's members. Members only.

    Who else is in a group is not public even when the library is: a public
    group publishes its contents, not the addresses of the people who made it.
    """
    if api_key is None or library.type is not LibraryType.GROUP:
        raise NotFoundError("Group not found")
    if await groups.membership(session, library, api_key.user_id) is None:
        raise NotFoundError("Group not found")

    return JSONResponse(
        [
            _member_payload(user, member)
            for user, member in await groups.list_members(session, library)
        ],
        headers=library_headers(library.version),
    )


async def _named_user(session: AsyncSession, payload: dict[str, Any]) -> User:
    """Return the account a membership request names.

    By id or by username: a caller holding a key knows its own user id, and one
    working from a list of people knows their names.
    """
    if (user_id := payload.get("userID")) is not None:
        if not isinstance(user_id, int):
            raise InvalidInputError("'userID' must be a user id")
        user = await session.get(User, user_id)
    elif (username := payload.get("username")) is not None:
        if not isinstance(username, str):
            raise InvalidInputError("'username' must be a string")
        from sqlalchemy import select

        user = await session.scalar(select(User).where(User.username == username))
    else:
        raise InvalidInputError("Either 'userID' or 'username' is required")

    if user is None:
        raise NotFoundError("No such user")
    return user


@router.post("/groups/{group_id}/users", status_code=201)
async def add_group_user(
    request: Request,
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
) -> Response:
    """Add somebody to the group. Administrators only.

    Adding an account outright rather than inviting it. The invitation flow the
    web interface uses is the one for an address that may not have an account
    here yet; this is the direct form, and it is why only an administrator can
    reach it.
    """
    await _admin(session, library, api_key)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise InvalidInputError("Uploaded data must be a JSON object")

    user = await _named_user(session, payload)
    library = await writes.lock_library(session, library)
    member = await groups.add_member(
        session,
        library,
        user,
        str(payload.get("role", "member")),
        str(payload.get("permission", MemberPermission.INHERIT.value)),
    )
    version = await writes.bump_library_version(session, library)
    await session.commit()

    return JSONResponse(
        _member_payload(user, member), status_code=201, headers=library_headers(version)
    )


@router.put("/groups/{group_id}/users/{member_id}")
async def set_group_user_role(
    member_id: int,
    request: Request,
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
) -> Response:
    """Change what one member may do. Administrators only."""
    await _admin(session, library, api_key)
    payload = await request.json()
    if not isinstance(payload, dict) or not {"role", "permission"} & set(payload):
        raise InvalidInputError("'role' or 'permission' is required")

    user = await auth.get_user(session, member_id)
    library = await writes.lock_library(session, library)

    # Role first, because promoting somebody clears their permission: a request
    # carrying both then ends on the permission it asked for rather than on the
    # `inherit` the promotion left behind.
    member = None
    if "role" in payload:
        member = await groups.set_role(session, library, user, str(payload["role"]))
    if "permission" in payload:
        member = await groups.set_permission(session, library, user, str(payload["permission"]))
    assert member is not None  # one of the two was present

    version = await writes.bump_library_version(session, library)
    await session.commit()

    return JSONResponse(_member_payload(user, member), headers=library_headers(version))


@router.delete("/groups/{group_id}/users/{member_id}", status_code=204)
async def remove_group_user(
    member_id: int,
    session: SessionDep,
    library: LibraryDep,
    api_key: ApiKeyDep,
) -> Response:
    """Take somebody out of the group.

    An administrator may remove anybody but the owner; anybody may remove
    themselves. Leaving a group is not an administrative act, and a member who
    had to ask permission to leave would be in a group they cannot get out of.
    """
    key = await _writer(session, library, api_key)
    if key.user_id != member_id:
        await groups.require_admin(session, library, key.user_id)

    user = await auth.get_user(session, member_id)
    library = await writes.lock_library(session, library)
    await groups.remove_member(session, library, user)
    version = await writes.bump_library_version(session, library)
    await session.commit()

    return Response(status_code=204, headers=library_headers(version))
