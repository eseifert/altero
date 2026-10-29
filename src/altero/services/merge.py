"""The item graph part of Zotero's duplicate merge.

Ported from Zotero 10.0.6's ``chrome/content/zotero/mergeItems.mjs``
(``mergeItems`` and ``moveRelations``). ``Zotero.Items.merge`` is now just a
wrapper around that module. The caller locks the library, supplies one new
version, and commits the transaction; every affected item uses ``save_item``.

This first part retains all attachments, including their embedded notes,
annotations and registered files. The desktop's PDF and web-attachment
deduplication is a separate step, not implemented here yet. There is no browser
route until that policy is settled.
"""

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import Item, ItemRelation, Library
from altero.serializers import timestamp
from altero.services import items, itemwrites
from altero.services.auth import Access

REPLACED = "dc:replaces"
_NON_REGULAR = frozenset({"attachment", "note", "annotation"})


def _validate(library: Library, master: Item, others: list[Item]) -> None:
    targets = [master, *others]
    if not others:
        raise InvalidInputError("Choose at least one other item to merge")
    if len({item.id for item in targets}) != len(targets):
        raise InvalidInputError("An item cannot be merged with itself or named twice")
    for item in targets:
        if item.library_id != library.id:
            raise InvalidInputError("Items being merged must be in the same library")
        if item.parent_id is not None or item.item_type in _NON_REGULAR:
            raise InvalidInputError("Only regular top-level items can be merged")
        if item.deleted:
            raise InvalidInputError("Restore items from the trash before merging them")
        # duplicatesMerge.js refuses mixed types before calling mergeItems.
        if item.item_type != master.item_type:
            raise InvalidInputError("Items being merged must have the same item type")


def _replace_note_key(note: str, old: str, new: str) -> str:
    """``Zotero.Notes.replaceItemKey``, including its non-global img replacement.

    Plain text, unencoded URLs and other attributes are left alone. Keys were
    validated when the items were created, so escaping is only defensive.
    """
    note = re.sub(r"%2Fitems%2F" + re.escape(old), lambda _: "%2Fitems%2F" + new, note)
    return re.sub(
        r'data-attachment-key="' + re.escape(old) + '"',
        lambda _: f'data-attachment-key="{new}"',
        note,
        count=1,
    )


def _relation_map(values: set[tuple[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for predicate, obj in sorted(values):
        result[predicate].append(obj)
    return dict(result)


async def merge_items(
    session: AsyncSession,
    library: Library,
    master: Item,
    others: list[Item],
    version: int,
    *,
    actor_id: int | None = None,
    permit: Access | None = None,
) -> list[Item]:
    """Keep ``master``, move the duplicates' children and links, then trash them.

    Keeps the master's fields and creators, takes the earliest ``dateAdded``,
    unions collections and tags (manual wins), transfers merge history, and
    redirects incoming relations within this library. Normal relations on the
    trashed originals remain, as on the desktop. Returns each changed item
    once, master first, all stamped with ``version``.

    The caller must hold the library lock and roll back on any exception.
    Permissions for the complete affected graph are checked before writing;
    ``save_item`` checks them again at each write. A confined credential cannot
    merge, because incoming relations can originate outside its collections.
    """
    _validate(library, master, others)
    if permit is not None:
        if permit.confined:
            raise ForbiddenError("Merging requires access to the whole library")
        permit.require_change(master.created_by_user_id)
        for other in others:
            permit.require_remove(other.created_by_user_id)

    targets = [master, *others]
    other_ids = [item.id for item in others]
    other_uris = [items.item_uri(library, item.key) for item in others]
    children = list(
        await session.scalars(select(Item).where(Item.parent_id.in_(other_ids)).order_by(Item.id))
    )
    incoming = list(
        await session.scalars(
            select(Item)
            .where(
                Item.library_id == library.id,
                Item.id != master.id,
                Item.id.in_(
                    select(ItemRelation.item_id).where(
                        ItemRelation.object.in_(other_uris), ItemRelation.predicate != REPLACED
                    )
                ),
            )
            .order_by(Item.id)
        )
    )
    affected = {item.id: item for item in [*targets, *children, *incoming]}
    if permit is not None:
        for item in affected.values():
            if item.item_type == "note" and not permit.notes:
                raise ForbiddenError("Merging these items requires access to their notes")
            permit.require_change(item.created_by_user_id)

    tags = await items.tags_for(session, targets)
    collections = await items.collection_keys_for(session, targets)
    # Plans are built from the stored graph, then written once per item. In
    # particular an incoming subject can also be a duplicate or a moved note.
    patches: dict[int, dict[str, Any]] = {item.id: {} for item in affected.values()}
    relation_sets = {
        item.id: {(relation.predicate, relation.object) for relation in item.relations}
        for item in affected.values()
    }
    before_relations = {item_id: set(values) for item_id, values in relation_sets.items()}
    master_uri = items.item_uri(library, master.key)
    combined_tags: dict[str, int] = {}
    combined_collections: set[str] = set()
    for item in targets:
        for name, kind in tags.get(item.id, []):
            if combined_tags.get(name) != 0:
                combined_tags[name] = kind
        combined_collections.update(collections.get(item.id, []))

    for child in children:
        patches[child.id]["parentItem"] = master.key
        if child.item_type == "note":
            old_parent = next(other for other in others if other.id == child.parent_id)
            patches[child.id]["note"] = _replace_note_key(
                child.field_values().get("note", ""), old_parent.key, master.key
            )

    # moveRelations: carry all outgoing links except links to the new subject;
    # transfer replaces exclusively, then update incoming links in this library.
    # Do not remove an existing master -> duplicate link: the desktop skips
    # the master's incoming relations rather than rewriting one into a self-link.
    for other, other_uri in zip(others, other_uris, strict=True):
        relation_sets[master.id].update(
            (pred, obj) for pred, obj in relation_sets[other.id] if obj != master_uri
        )
        relation_sets[other.id] = {
            (pred, obj) for pred, obj in relation_sets[other.id] if pred != REPLACED
        }
        for subject in affected.values():
            if subject.id == master.id:
                continue
            relation_sets[subject.id] = {
                (pred, master_uri if obj == other_uri and pred != REPLACED else obj)
                for pred, obj in relation_sets[subject.id]
            }
        relation_sets[master.id].add((REPLACED, other_uri))
        patches[other.id]["deleted"] = True

    patches[master.id].update(
        dateAdded=timestamp(min(item.date_added for item in targets)),
        tags=[{"tag": name, "type": kind} for name, kind in combined_tags.items()],
        collections=sorted(combined_collections),
    )
    for item_id, values in relation_sets.items():
        if values != before_relations[item_id]:
            patches[item_id]["relations"] = _relation_map(values)

    written = []
    for item in affected.values():
        if not patches[item.id]:
            continue
        await itemwrites.save_item(
            session,
            library,
            patches[item.id],
            version,
            key=item.key,
            replace=False,
            actor_id=actor_id,
            permit=permit,
            stored=item,
        )
        written.append(item)
    return written
