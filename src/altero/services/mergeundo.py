"""Restore only the server's inverse of its last browser merge.

The caller holds the library lock throughout capture, merge and remember, or
throughout restore. One row per library bounds storage even without a sweep.
The row is not archived and cannot survive clearing/restoring a library.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, NotFoundError, PreconditionFailedError
from altero.models import Item, Library, MergeUndo
from altero.serializers import timestamp
from altero.services import items, itemwrites, writes
from altero.services.auth import Access


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def capture(
    session: AsyncSession, affected: list[Item], patches: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Read old values for precisely the properties the merge will write."""
    tags = await items.tags_for(session, affected)
    collections = await items.collection_keys_for(session, affected)
    parents = await items.parent_keys_for(session, affected)
    inverse = []
    for item in affected:
        patch = patches[item.id]
        if not patch:
            continue
        values: dict[str, Any] = {
            **item.field_values(),
            "dateAdded": timestamp(item.date_added),
            "deleted": item.deleted,
            "parentItem": parents.get(item.parent_id, False),
            "collections": collections.get(item.id, []),
            "tags": [{"tag": name, "type": kind} for name, kind in tags.get(item.id, [])],
            "creators": [
                {"creatorType": creator.creator_type, "name": creator.name}
                if creator.name is not None
                else {
                    "creatorType": creator.creator_type,
                    "firstName": creator.first_name or "",
                    "lastName": creator.last_name or "",
                }
                for creator in sorted(item.creators, key=lambda creator: creator.position)
            ],
            "relations": {},
        }
        for relation in item.relations:
            values["relations"].setdefault(relation.predicate, []).append(relation.object)
        inverse.append({"key": item.key, **{name: values.get(name, "") for name in patch}})
    return inverse


async def remember(
    session: AsyncSession, library: Library, user_id: int, patches: list[dict[str, Any]]
) -> None:
    row = await session.get(MergeUndo, library.id)
    if row is None:
        row = MergeUndo(library_id=library.id)
        session.add(row)
    row.user_id = user_id
    row.version = library.version
    row.patches = patches
    row.expires = now() + timedelta(minutes=5)
    await session.flush()


async def restore(
    session: AsyncSession, library: Library, user_id: int, expected: int, permit: Access
) -> list[Item]:
    """Consume an intact snapshot, applying all changes at one new version.

    Ordinary validation and permissions apply to every item again. Any refusal
    rolls the transaction back, including the snapshot's consumption.
    """
    if library.version != expected:
        raise PreconditionFailedError("The library has changed; undo is no longer available")
    row = await session.get(MergeUndo, library.id)
    if row is None or row.user_id != user_id or row.expires <= now():
        raise NotFoundError("Merge undo is no longer available")
    if row.version != expected:
        raise PreconditionFailedError("The library has changed; undo is no longer available")
    if permit.confined:
        raise ForbiddenError("Undoing a merge requires access to the whole library")
    targets = await items.get_items(
        session, library, [patch["key"] for patch in row.patches], permit=permit
    )
    version = await writes.bump_library_version(session, library)
    for item, patch in zip(targets, row.patches, strict=True):
        if item.item_type == "note" and not permit.notes:
            raise ForbiddenError("Undoing this merge requires access to its notes")
        await itemwrites.save_item(
            session,
            library,
            {name: value for name, value in patch.items() if name != "key"},
            version,
            key=item.key,
            replace=False,
            actor_id=user_id,
            permit=permit,
            stored=item,
        )
    await session.delete(row)
    return targets
