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
from altero.models import ApiKey, Group, GroupMember, Library, LibraryType, User
from altero.services import auth, groups, writes

router = APIRouter(tags=["groups"])


def _member_payload(user: User, member: GroupMember) -> dict[str, Any]:
    """Render one member.

    A shape of altero's own: upstream answers ``403`` here to anything an API
    key can present, so there is nothing to copy. It names the account the way
    ``/keys/<key>`` does, so the two read alike.
    """
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "role": member.role,
    }


async def _writer(session: AsyncSession, library: Library, api_key: ApiKey | None) -> ApiKey:
    """Return the key, requiring that it may write to this group at all.

    Separate from the admin check and made first, so that a read-only key is
    told it cannot write rather than that it is not an administrator -- which
    would be misleading for somebody who is one.
    """
    if api_key is None:
        raise ForbiddenError("Forbidden")
    if library.type is not LibraryType.GROUP:
        raise InvalidInputError("Only a group library has members")
    if not (await auth.get_access(session, library, api_key)).write:
        raise ForbiddenError("This key may not write to this group")
    return api_key


async def _admin(session: AsyncSession, library: Library, api_key: ApiKey | None) -> User:
    """Return the account administering this group through ``api_key``."""
    key = await _writer(session, library, api_key)
    await groups.require_admin(session, library, key.user_id)
    return await auth.get_user(session, key.user_id)


async def _rendered(
    session: AsyncSession, library: Library, base_url: str, group: Group | None = None
) -> dict[str, Any]:
    return serializers.group(library, group or await groups.get_group(session, library), base_url)


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

    return object_response(await _rendered(session, library, base_url), library.version)


@router.get("/users/{user_id}/groups")
async def list_user_groups(
    user_id: int,
    session: SessionDep,
    api_key: ApiKeyDep,
    base_url: BaseUrlDep,
) -> list[dict[str, Any]]:
    """Return the groups a user belongs to.

    Only the user themselves may list their groups.
    """
    if api_key is None or api_key.user_id != user_id:
        raise ForbiddenError("Forbidden")

    await auth.get_user(session, user_id)
    memberships = await groups.list_groups_for_user(session, user_id)

    return [serializers.group(library, group, base_url) for library, group in memberships]


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
    if not (await auth.get_access(session, personal, api_key)).write:
        raise ForbiddenError("This key may not create groups")

    owner = await auth.get_user(session, api_key.user_id)
    library, group = await groups.create_group(session, owner=owner, payload=await _body(request))
    await session.commit()

    return JSONResponse(
        serializers.group(library, group, base_url),
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
    api_key: ApiKey | None,
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

    return object_response(serializers.group(library, group, base_url), version)


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
    member = await groups.add_member(session, library, user, payload.get("role", "member"))
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
    if not isinstance(payload, dict) or "role" not in payload:
        raise InvalidInputError("'role' is required")

    user = await auth.get_user(session, member_id)
    library = await writes.lock_library(session, library)
    member = await groups.set_role(session, library, user, payload["role"])
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
