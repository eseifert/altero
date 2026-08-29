"""Reading and writing attachment full-text content."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import InvalidInputError, NotFoundError
from altero.models import FullText, Item, Library
from altero.services.auth import Access
from altero.services.items import confined_to_collections, get_item

#: Counts the client may report alongside the content. Only those it sends are
#: stored, and only those stored are returned.
STATISTICS = ("indexedChars", "totalChars", "indexedPages", "totalPages")

_COLUMNS = {
    "indexedChars": "indexed_chars",
    "totalChars": "total_chars",
    "indexedPages": "indexed_pages",
    "totalPages": "total_pages",
}


async def get_content(session: AsyncSession, item: Item) -> FullText:
    """Return the stored text of one attachment."""
    stored = await session.get(FullText, item.id)
    if stored is None:
        raise NotFoundError("Not found")
    return stored


def render(stored: FullText) -> dict[str, Any]:
    """Return the JSON form, omitting statistics the client never sent."""
    payload: dict[str, Any] = {"content": stored.content}
    for name, column in _COLUMNS.items():
        value = getattr(stored, column)
        if value is not None:
            payload[name] = value
    return payload


async def save_content(
    session: AsyncSession,
    library: Library,
    item: Item,
    payload: Any,
    version: int,
    *,
    permit: Access | None = None,
) -> FullText:
    """Store the text of one attachment.

    Indexed text is part of the attachment rather than a thing of its own, so a
    member restricted to their own items may not overwrite anybody else's.
    """
    if permit is not None:
        permit.require_change(item.created_by_user_id)

    if not isinstance(payload, dict) or "content" not in payload:
        raise InvalidInputError("'content' property not provided")

    stored = await session.get(FullText, item.id)
    if stored is None:
        stored = FullText(item_id=item.id, library_id=library.id)
        session.add(stored)

    stored.content = str(payload["content"])
    stored.version = version
    for name, column in _COLUMNS.items():
        value = payload.get(name)
        if value is not None:
            try:
                setattr(stored, column, int(value))
            except TypeError, ValueError:
                raise InvalidInputError(f"Invalid '{name}' value '{value}'") from None

    await session.flush()
    return stored


async def save_batch_entry(
    session: AsyncSession,
    library: Library,
    payload: Any,
    version: int,
    *,
    permit: Access | None = None,
) -> dict[str, Any]:
    """Store one entry of a batch upload and return its result object.

    The entry names its own item by key rather than the URL doing it, so the
    lookup and its failure belong here.
    """
    if not isinstance(payload, dict):
        raise InvalidInputError("Invalid full-text object")

    key = payload.get("key")
    if not key:
        raise InvalidInputError("Item key not provided")

    item = await get_item(session, library, str(key), permit=permit)
    await save_content(session, library, item, payload, version, permit=permit)

    # The client reads `.key` off every successful and unchanged entry, so this
    # is an object rather than a bare key.
    return {"key": item.key}


async def list_versions(
    session: AsyncSession, library: Library, since: int = 0, *, permit: Access | None = None
) -> dict[str, int]:
    """Return the version of every attachment's text, keyed by item key.

    A client syncs its search index from this the same way it syncs objects.

    ``permit`` narrows it to what the caller may see. This answer is a list of
    item keys and versions, so a resource-scoped grant has to reach it: leaving
    it alone would hand an application the key of every indexed attachment in a
    library it was given one collection of.
    """
    statement = (
        select(Item.key, FullText.version)
        .join(FullText, FullText.item_id == Item.id)
        .where(FullText.library_id == library.id)
    )
    if permit is not None and permit.collections is not None:
        statement = statement.where(confined_to_collections(permit.collections))
    if since:
        statement = statement.where(FullText.version > since)

    result = await session.execute(statement.order_by(Item.key))
    return {key: version for key, version in result.all()}
