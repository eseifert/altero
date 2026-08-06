"""The delete log behind ``/deleted?since=``."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import DeletedObject, DeletedObjectType, Library


async def record_deletion(
    session: AsyncSession,
    library: Library,
    object_type: DeletedObjectType,
    key: str,
    version: int,
) -> None:
    """Note that ``key`` was removed at ``version``.

    Deleting a key that was deleted before moves the existing entry forward
    rather than adding a second one, matching the primary key the dataserver
    puts on this table.
    """
    existing = await session.scalar(
        select(DeletedObject).where(
            DeletedObject.library_id == library.id,
            DeletedObject.object_type == object_type,
            DeletedObject.key == key,
        )
    )
    if existing is not None:
        existing.version = version
        return

    session.add(
        DeletedObject(
            library_id=library.id,
            object_type=str(object_type),
            key=key,
            version=version,
        )
    )


async def forget_deletion(
    session: AsyncSession,
    library: Library,
    object_type: DeletedObjectType,
    key: str,
) -> None:
    """Drop any record that ``key`` was removed, because it exists again.

    A tag is its name, so a name that comes back -- typed onto an item again,
    or arrived at by renaming another tag -- is the deleted tag returning. The
    entry has to go with it: a client that reads ``/deleted?since=`` after both
    changes would otherwise be told to remove the very tag the items it fetched
    in the same sync are carrying, and which of the two it applied last would
    decide whether the tag survived. The dataserver clears the same row for the
    same reason, in ``Zotero_Tag::save``.
    """
    await session.execute(
        delete(DeletedObject).where(
            DeletedObject.library_id == library.id,
            DeletedObject.object_type == object_type,
            DeletedObject.key == key,
        )
    )


async def list_deletions(
    session: AsyncSession,
    library: Library,
    since: int,
) -> dict[str, list[str]]:
    """Return everything removed since ``since``, grouped by object type.

    Every group is present even when empty, so a client can iterate the response
    without checking for missing keys.
    """
    result = await session.scalars(
        select(DeletedObject)
        .where(DeletedObject.library_id == library.id, DeletedObject.version > since)
        .order_by(DeletedObject.key)
    )

    grouped: dict[str, list[str]] = {
        "collections": [],
        "items": [],
        "searches": [],
        "settings": [],
        "tags": [],
    }
    plural = {
        DeletedObjectType.COLLECTION: "collections",
        DeletedObjectType.ITEM: "items",
        DeletedObjectType.SEARCH: "searches",
        DeletedObjectType.SETTING: "settings",
        DeletedObjectType.TAG: "tags",
    }
    for entry in result:
        group = plural.get(DeletedObjectType(entry.object_type))
        if group:
            grouped[group].append(entry.key)
    return grouped
