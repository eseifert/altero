"""Plan the attachment steps of Zotero 10.0.6's ``mergeItems.mjs``.

The plan changes no rows or files. The enclosing merge preflights permissions
for every affected object before applying it, together with the item graph.
Byte hashes come from registered files, never an item's client-supplied md5.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from icu import Collator, Locale  # ty: ignore[unresolved-import]

from altero.models import Item
from altero.services import pdfmerge, storage


@dataclass(slots=True)
class AttachmentPlan:
    patches: dict[int, dict[str, Any]] = field(default_factory=dict)
    relation_moves: list[tuple[Item, Item]] = field(default_factory=list)
    remap: dict[str, str] = field(default_factory=dict)
    #: Embedded notes promoted to child notes, with their original parent key.
    notes: list[tuple[str, str]] = field(default_factory=list)

    def patch(self, item: Item) -> dict[str, Any]:
        return self.patches.setdefault(item.id, {})


def _is_pdf(item: Item) -> bool:
    values = item.field_values()
    return values.get("linkMode") != "linked_url" and values.get("contentType") == "application/pdf"


def _is_web(item: Item) -> bool:
    return item.field_values().get("linkMode") not in {"imported_file", "linked_file"}


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()


async def plan_attachments(
    master: Item,
    others: list[Item],
    children: list[Item],
    grandchildren: list[Item],
    root: Path | None,
    *,
    locale: str,
    cached_text: dict[int, str],
) -> AttachmentPlan:
    """PDFs, then web attachments, then all remaining attachment types.

    Follows the pinned client's order and matching maps, including its title
    fallback for linked URLs. Linked files are retained: their local paths
    cannot be read by a server. Missing or unreadable PDFs are retained too.
    """
    from altero.services.merge import _replace_note_key

    plan = AttachmentPlan()
    collator = Collator.createInstance(Locale.forLanguageTag(locale))
    collator.setStrength(Collator.PRIMARY)
    attachments = sorted(
        (item for item in children if item.item_type == "attachment"),
        key=lambda item: (collator.getSortKey(item.field_values().get("title", "")), item.id),
    )
    files: dict[int, Path | None] = {}
    byte_hashes: dict[Path, str | None] = {}
    parsed: dict[tuple[Path, bool], pdfmerge.PDFInfo] = {}
    parent_keys = {item.id: item.key for item in [master, *others, *attachments]}

    def parent_key(item: Item) -> str | None:
        return plan.patches.get(item.id, {}).get("parentItem", parent_keys.get(item.parent_id))

    def path_of(item: Item) -> Path | None:
        if item.id not in files:
            mode = item.field_values().get("linkMode")
            digest = (
                storage.stored_md5(item, root)
                if root is not None and mode in {"imported_file", "imported_url"}
                else None
            )
            files[item.id] = (
                storage.file_path(root, digest) if root is not None and digest else None
            )
        return files[item.id]

    async def byte_hash(item: Item) -> str | None:
        path = path_of(item)
        if path is None:
            return None
        if path not in byte_hashes:
            try:
                byte_hashes[path] = await asyncio.to_thread(_digest, path)
            except OSError:
                byte_hashes[path] = None
        return byte_hashes[path]

    async def inspect(item: Item, *, text: bool) -> pdfmerge.PDFInfo:
        path = path_of(item)
        if path is None:
            return pdfmerge.PDFInfo()
        if (path, True) in parsed:
            return parsed[(path, True)]
        key = path, text
        if key not in parsed:
            parsed[key] = await pdfmerge.inspect_pdf(path, locale, text=text)
        return parsed[key]

    async def text_hash(item: Item) -> str | None:
        path = path_of(item)
        if path is None:
            return None
        try:
            if path.stat().st_size > pdfmerge.MAX_TEXT_FILE_SIZE:
                return None
            if item.id in cached_text:
                return await asyncio.to_thread(pdfmerge.hash_text, cached_text[item.id], locale)
            if _is_pdf(item):
                return (await inspect(item, text=True)).text_hash
            if item.field_values().get("contentType") == "text/plain":
                text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
                return await asyncio.to_thread(pdfmerge.hash_text, text, locale)
        except OSError:
            return None
        return None

    def active_on_master(item: Item) -> bool:
        patch = plan.patches.get(item.id, {})
        return not patch.get("deleted", item.deleted) and parent_key(item) == master.key

    async def hashes(*, text: bool) -> dict[str, Item]:
        result: dict[str, Item] = {}
        for item in attachments:
            if active_on_master(item) and item.field_values().get("linkMode") != "linked_url":
                value = await text_hash(item) if text else await byte_hash(item)
                if value:
                    result[value] = item
        return result

    # mergePDFAttachments: a fixed initial byte map, lazily extended by the
    # current master's text map on the first byte mismatch, as in Zotero.
    master_hashes = await hashes(text=False)
    includes_text = False
    for other in others:
        used: set[int] = set()
        for item in attachments:
            if item.parent_id != other.id or not _is_pdf(item):
                continue
            if item.deleted:
                plan.patch(item)["parentItem"] = master.key
                continue
            target = master_hashes.get(await byte_hash(item) or "")
            if target is None and any(active_on_master(item) for item in attachments):
                if not includes_text:
                    master_hashes.update(await hashes(text=True))
                    includes_text = True
                target = master_hashes.get(await text_hash(item) or "")
            if target is None or target.id in used:
                plan.patch(item)["parentItem"] = master.key
                continue
            target_values, values = target.field_values(), item.field_values()
            if target_values.get("contentType") != values.get("contentType"):
                plan.patch(item)["parentItem"] = master.key
                continue
            imported = {"imported_file", "imported_url"}
            if not (
                target_values.get("linkMode") in imported and values.get("linkMode") in imported
            ):
                plan.patch(item)["parentItem"] = master.key
                continue
            source = item
            swapped = False
            if (await inspect(item, text=False)).has_annotations:
                if (await inspect(target, text=False)).has_annotations:
                    plan.patch(item)["parentItem"] = master.key
                    continue
                source, target = target, item
                swapped = True
            used.add(target.id)
            for child in grandchildren:
                if parent_key(child) == source.key:
                    plan.patch(child)["parentItem"] = target.key
            # moveEmbeddedNote: keep an existing target note, promote the
            # source note to a child in that case, and remap its attachment URL.
            note = plan.patches.get(source.id, {}).get(
                "note", source.field_values().get("note", "")
            )
            if note:
                note = _replace_note_key(note, source.key, target.key)
                target_note = plan.patches.get(target.id, {}).get(
                    "note", target.field_values().get("note", "")
                )
                if target_note:
                    target_parent = parent_key(target)
                    assert target_parent is not None
                    plan.notes.append((target_parent, note))
                else:
                    plan.patch(target)["note"] = note
                plan.patch(source)["note"] = ""
            plan.relation_moves.append((source, target))
            plan.patch(source)["deleted"] = True
            plan.remap[source.key] = target.key
            if swapped:
                plan.patch(target)["parentItem"] = master.key

    # mergeWebAttachments: unlike PDF matching, consume a master attachment
    # only once across the whole merge. A missing master snapshot is not used.
    web = [
        item
        for item in attachments
        if active_on_master(item)
        and _is_web(item)
        and (item.field_values().get("linkMode") == "linked_url" or path_of(item) is not None)
    ]
    for other in others:
        for item in attachments:
            if parent_key(item) != other.key or not _is_web(item):
                continue
            values = item.field_values()
            candidates = [
                target
                for target in web
                if target.field_values().get("title", "") == values.get("title", "")
                and target.field_values().get("linkMode") == values.get("linkMode")
            ]
            target = next(
                (
                    target
                    for target in candidates
                    if target.field_values().get("url", "") == values.get("url", "")
                ),
                next(iter(candidates), None),
            )
            if plan.patches.get(item.id, {}).get("deleted", item.deleted) or target is None:
                plan.patch(item)["parentItem"] = master.key
                continue
            plan.patch(item)["deleted"] = True
            plan.relation_moves.append((item, target))
            web.remove(target)

    # mergeOtherAttachments, which also preserves attachments with no bytes.
    for item in attachments:
        if item.parent_id != master.id and not _is_pdf(item) and not _is_web(item):
            plan.patch(item)["parentItem"] = master.key
    return plan
