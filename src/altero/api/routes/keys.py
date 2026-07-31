"""Endpoints describing API keys and group membership."""

from typing import Any

from fastapi import APIRouter

from altero import serializers
from altero.api.deps import ApiKeyDep, BaseUrlDep, SessionDep
from altero.errors import ForbiddenError
from altero.models import Library
from altero.services import auth, groups

router = APIRouter(tags=["keys"])


@router.get("/keys/{key}")
async def get_key(key: str, session: SessionDep, api_key: ApiKeyDep) -> dict[str, Any]:
    """Return the access granted by an API key.

    A key may only be inspected by a request authenticated with that same key.
    """
    if api_key is None or api_key.key != key:
        raise ForbiddenError("Forbidden")

    user = await auth.get_user(session, api_key.user_id)

    # Per-group overrides are stored against the internal library id, but the
    # response identifies groups by the id that appears in URLs.
    overrides: dict[int, dict[str, bool]] = {}
    for entry in await auth.list_group_overrides(session, api_key):
        library = await session.get(Library, entry.library_id)
        if library is not None:
            overrides[library.owner_id] = {"library": entry.read, "write": entry.write}

    return serializers.api_key(api_key, user, overrides)


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
