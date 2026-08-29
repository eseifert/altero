"""Reading and writing library settings."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import DeletedObjectType, Library, Setting
from altero.services.auth import Access
from altero.services.deletions import record_deletion
from altero.services.writes import check_object_version

#: Longest a setting name may be, matching the column the dataserver uses.
MAX_NAME_LENGTH = 60


async def get_setting(
    session: AsyncSession, library: Library, name: str, *, permit: Access | None = None
) -> Setting:
    """Return one setting by name.

    A confined credential finds none. See :func:`list_settings`.
    """
    if permit is not None and permit.collections is not None:
        raise NotFoundError("Setting not found")

    setting = await session.scalar(
        select(Setting).where(Setting.library_id == library.id, Setting.name == name)
    )
    if setting is None:
        raise NotFoundError("Setting not found")
    return setting


async def list_settings(
    session: AsyncSession, library: Library, since: int = 0, *, permit: Access | None = None
) -> list[Setting]:
    """Return the library's settings, optionally only those newer than ``since``.

    A credential confined to some collections sees none. A setting is the
    library's -- tag colours, the feed list, what the client shows -- and none
    of it belongs to a collection, so there is no part of it a grant to one
    collection has been given.
    """
    if permit is not None and permit.collections is not None:
        return []

    statement = select(Setting).where(Setting.library_id == library.id)
    if since:
        statement = statement.where(Setting.version > since)
    return list(await session.scalars(statement.order_by(Setting.name)))


def render(setting: Setting) -> dict[str, Any]:
    """Return the JSON form of one setting."""
    return {"value": json.loads(setting.value), "version": setting.version}


def render_all(settings: list[Setting]) -> dict[str, Any]:
    """Return the JSON form of a whole collection of settings, keyed by name."""
    return {setting.name: render(setting) for setting in settings}


async def save_setting(
    session: AsyncSession,
    library: Library,
    name: str,
    payload: Any,
    version: int,
    *,
    require_version: bool = False,
    permit: Access | None = None,
) -> Setting:
    """Create or replace one setting.

    The body is ``{"value": ...}``; anything JSON-encodable is accepted, since
    the server never interprets what a setting means.

    A setting belongs to the library rather than to whoever wrote it -- tag
    colours are the one the desktop client uses -- so it follows the same rule
    as the collections and saved searches beside it.
    """
    if permit is not None:
        permit.require_change_structure()

    if not name or len(name) > MAX_NAME_LENGTH:
        raise InvalidInputError(f"Invalid setting name '{name}'")
    if not isinstance(payload, dict) or "value" not in payload:
        raise InvalidInputError(f"Invalid setting '{name}'")

    setting = await session.scalar(
        select(Setting).where(Setting.library_id == library.id, Setting.name == name)
    )
    if setting is None:
        setting = Setting(library_id=library.id, name=name)
        session.add(setting)
    else:
        check_object_version(setting.version, payload.get("version"), required=require_version)

    try:
        setting.value = json.dumps(payload["value"])
    except TypeError, ValueError:
        raise InvalidInputError(f"Value of setting '{name}' is not JSON") from None

    setting.version = version
    await session.flush()
    return setting


async def delete_settings(
    session: AsyncSession,
    library: Library,
    names: list[str],
    version: int,
    *,
    permit: Access | None = None,
) -> None:
    """Remove settings by name and record the deletions."""
    if permit is not None:
        permit.require_remove_structure()

    for name in names:
        setting = await session.scalar(
            select(Setting).where(Setting.library_id == library.id, Setting.name == name)
        )
        if setting is None:
            continue
        await session.delete(setting)
        await record_deletion(session, library, DeletedObjectType.SETTING, name, version)
