"""The delete log behind ``/deleted?since=``."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import DeletedObject, DeletedObjectType, Library
from altero.services.auth import Access


def _empty() -> dict[str, list[str]]:
    """Return the shape of the answer, with nothing in it."""
    return {"collections": [], "items": [], "searches": [], "settings": [], "tags": []}


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
    *,
    permit: Access | None = None,
) -> dict[str, list[str]]:
    """Return everything removed since ``since``, grouped by object type.

    Every group is present even when empty, so a client can iterate the response
    without checking for missing keys.

    A credential confined to some collections is told nothing was removed, and
    that is the only sound answer this table can give one. What is left of a
    deleted object is its key: the row that said which collections it was in
    went with it, so there is no way to ask whether it was inside the grant.
    Answering with the keys anyway would hand an application a running list of
    everything removed from the parts of the library it was not given.
    ``docs/compatibility.md`` records it.
    """
    if permit is not None and permit.collections is not None:
        return _empty()

    result = await session.scalars(
        select(DeletedObject)
        .where(DeletedObject.library_id == library.id, DeletedObject.version > since)
        .order_by(DeletedObject.key)
    )

    grouped = _empty()
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
