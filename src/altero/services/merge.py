"""The item graph part of Zotero's duplicate merge.

Ported from Zotero 10.0.6's ``chrome/content/zotero/mergeItems.mjs``
(``mergeItems`` and ``moveRelations``). ``Zotero.Items.merge`` is now just a
wrapper around that module. The caller locks the library, supplies one new
version, and commits the transaction; every affected item uses ``save_item``.

Attachment decisions live in ``mergeattachments``; PDF inspection runs in a
disposable worker. All decisions are planned before any item is written.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.itemschema import get_schema
from altero.models import FullText, Item, ItemRelation, Library
from altero.serializers import timestamp
from altero.services import items, itemwrites, mergeattachments
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
    return _replace_note_keys(note, {old: new})


def _replace_note_keys(note: str, keys: dict[str, str]) -> str:
    if not keys:
        return note
    alternatives = "|".join(re.escape(key) for key in keys)
    note = re.sub(
        r"%2Fitems%2F(" + alternatives + ")", lambda match: "%2Fitems%2F" + keys[match[1]], note
    )
    return re.sub(
        r'data-attachment-key="(' + alternatives + ')"',
        lambda match: f'data-attachment-key="{keys[match[1]]}"',
        note,
        count=1,
    )


def _relation_map(values: set[tuple[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for predicate, obj in sorted(values):
        result[predicate].append(obj)
    return dict(result)


def _move_relations(
    library: Library,
    relations: dict[int, set[tuple[str, str]]],
    source: Item,
    target: Item,
) -> None:
    source_uri, target_uri = (items.item_uri(library, item.key) for item in (source, target))
    relations[target.id].update(
        (pred, obj) for pred, obj in relations[source.id] if obj != target_uri
    )
    relations[source.id] = {(pred, obj) for pred, obj in relations[source.id] if pred != REPLACED}
    for subject_id, values in relations.items():
        if subject_id != target.id:
            relations[subject_id] = {
                (pred, target_uri if obj == source_uri and pred != REPLACED else obj)
                for pred, obj in values
            }
    relations[target.id].add((REPLACED, source_uri))


async def merge_items(
    session: AsyncSession,
    library: Library,
    master: Item,
    others: list[Item],
    version: int,
    *,
    actor_id: int | None = None,
    permit: Access | None = None,
    storage_root: Path | None = None,
    locale: str = "en-US",
    fields: dict[str, Any] | None = None,
) -> list[Item]:
    """Keep ``master``, move the duplicates' children and links, then trash them.

    Keeps the master's fields and creators unless ``fields`` chooses others,
    takes the earliest ``dateAdded``,
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
    chosen = fields or {}
    allowed = get_schema().get_item_type(master.item_type).field_names
    for name, value in chosen.items():
        if name != "creators":
            if name not in allowed:
                raise InvalidInputError(f"'{name}' cannot be chosen in a merge")
            if value is not None and not isinstance(value, str):
                raise InvalidInputError(f"'{name}' must be text or null")
    # Includes creator shape/type checks, before any file parsing or writes.
    itemwrites.validate_item(chosen, master, library.type)
    if permit is not None:
        if permit.confined:
            raise ForbiddenError("Merging requires access to the whole library")
        permit.require_change(master.created_by_user_id)
        for other in others:
            permit.require_remove(other.created_by_user_id)

    targets = [master, *others]
    other_ids = [item.id for item in others]
    children = list(
        await session.scalars(
            select(Item).where(Item.parent_id.in_([item.id for item in targets])).order_by(Item.id)
        )
    )
    attachments = [item for item in children if item.item_type == "attachment"]
    grandchildren = list(
        await session.scalars(
            select(Item)
            .where(Item.parent_id.in_([item.id for item in attachments]))
            .order_by(Item.id)
        )
    )
    old_uris = [items.item_uri(library, item.key) for item in [*others, *attachments]]
    incoming = list(
        await session.scalars(
            select(Item)
            .where(
                Item.library_id == library.id,
                Item.id.in_(
                    select(ItemRelation.item_id).where(
                        ItemRelation.object.in_(old_uris), ItemRelation.predicate != REPLACED
                    )
                ),
            )
            .order_by(Item.id)
        )
    )
    affected = {item.id: item for item in [*targets, *children, *grandchildren, *incoming]}
    cached_text = dict(
        (
            await session.execute(
                select(FullText.item_id, FullText.content).where(
                    FullText.item_id.in_([item.id for item in attachments])
                )
            )
        )
        .tuples()
        .all()
    )
    attachment_plan = await mergeattachments.plan_attachments(
        master,
        others,
        children,
        grandchildren,
        storage_root,
        locale=locale,
        cached_text=cached_text,
    )

    tags = await items.tags_for(session, targets)
    collections = await items.collection_keys_for(session, targets)
    # Plans are built from the stored graph, then written once per item. In
    # particular an incoming subject can also be a duplicate or a moved note.
    patches: dict[int, dict[str, Any]] = {item.id: {} for item in affected.values()}
    patches[master.id].update(chosen)
    patches.update(attachment_plan.patches)
    relation_sets = {
        item.id: {(relation.predicate, relation.object) for relation in item.relations}
        for item in affected.values()
    }
    before_relations = {item_id: set(values) for item_id, values in relation_sets.items()}
    combined_tags: dict[str, int] = {}
    combined_collections: set[str] = set()
    for item in targets:
        for name, kind in tags.get(item.id, []):
            if combined_tags.get(name) != 0:
                combined_tags[name] = kind
        combined_collections.update(collections.get(item.id, []))

    for child in children:
        if child.parent_id in other_ids and child.item_type == "note":
            patches[child.id]["parentItem"] = master.key
            old_parent = next(other for other in others if other.id == child.parent_id)
            patches[child.id]["note"] = _replace_note_keys(
                _replace_note_key(child.field_values().get("note", ""), old_parent.key, master.key),
                attachment_plan.remap,
            )

    for source, target in attachment_plan.relation_moves:
        _move_relations(library, relation_sets, source, target)

    # moveRelations: carry all outgoing links except links to the new subject;
    # transfer replaces exclusively, then update incoming links in this library.
    # Do not remove an existing master -> duplicate link: the desktop skips
    # the master's incoming relations rather than rewriting one into a self-link.
    for other in others:
        _move_relations(library, relation_sets, other, master)
        patches[other.id]["deleted"] = True

    patches[master.id].update(
        dateAdded=timestamp(min(item.date_added for item in targets)),
        tags=[{"tag": name, "type": kind} for name, kind in combined_tags.items()],
        collections=sorted(combined_collections),
    )
    for item_id, values in relation_sets.items():
        if values != before_relations[item_id]:
            patches[item_id]["relations"] = _relation_map(values)

    if permit is not None:
        if attachment_plan.notes and not permit.notes:
            raise ForbiddenError("Merging these items requires access to their notes")
        for item in affected.values():
            if not patches[item.id]:
                continue
            if item.item_type == "note" and not permit.notes:
                raise ForbiddenError("Merging these items requires access to their notes")
            permit.require_change(item.created_by_user_id)
            if patches[item.id].get("deleted"):
                permit.require_remove(item.created_by_user_id)

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
    for parent_key, note in attachment_plan.notes:
        if parent_key != master.key:
            note = _replace_note_keys(
                _replace_note_key(note, parent_key, master.key), attachment_plan.remap
            )
        item = await itemwrites.save_item(
            session,
            library,
            {"itemType": "note", "parentItem": master.key, "note": note},
            version,
            actor_id=actor_id,
            permit=permit,
        )
        assert item is not None
        written.append(item)
    return written
