"""Attachment decisions from Zotero 10.0.6's mergeItems.mjs, with real files."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError
from altero.models import Item, Library
from altero.services import items, merge, storage, writes
from altero.services.auth import Access
from tests import factories
from tests.test_merge import library as library
from tests.test_merge import relations, set_relations
from tests.test_pdfmerge import TEXT, pdf_bytes


async def attachment(
    session: AsyncSession,
    library: Library,
    parent: Item,
    root: Path,
    *,
    body: bytes | None = None,
    mode: str = "imported_file",
    title: str = "PDF",
    content_type: str = "application/pdf",
    deleted: bool = False,
    note: str = "",
    url: str = "https://example.org/",
    registered: bool = True,
) -> Item:
    body = pdf_bytes() if body is None else body
    digest = storage.file_digest(body)
    if registered and mode != "linked_url":
        storage.store_file(root, digest, body)
    return await factories.make_item(
        session,
        library,
        item_type="attachment",
        parent=parent,
        deleted=deleted,
        registered=registered,
        fields={
            "linkMode": mode,
            "title": title,
            "contentType": content_type,
            "md5": digest,
            "mtime": "4242",
            "filename": "paper.pdf",
            "url": url,
            "note": note,
        },
    )


async def merged(
    session: AsyncSession,
    library: Library,
    master: Item,
    others: list[Item],
    root: Path,
    *,
    permit: Access | None = None,
) -> list[Item]:
    await writes.lock_library(session, library)
    version = await writes.bump_library_version(session, library)
    changed = await merge.merge_items(
        session, library, master, others, version, storage_root=root, permit=permit
    )
    await session.commit()
    return changed


async def test_keeps_both_pdfs_when_swapping_would_move_a_parent_and_change_a_note(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    """Zotero 10.0.6 loses that parent move when saving the changed note."""
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    original = await attachment(session, library, master, tmp_path, note="<p>Keep this note</p>")
    marked = await attachment(session, library, other, tmp_path, body=pdf_bytes(subtype="/Text"))
    annotation = await factories.make_item(
        session,
        library,
        item_type="annotation",
        parent=original,
        fields={"annotationType": "highlight"},
    )
    await session.commit()
    await merged(session, library, master, [other], tmp_path)
    assert not original.deleted, "The original PDF and its note must remain together"
    assert not marked.deleted
    assert original.parent_id == marked.parent_id == master.id
    assert original.field_values()["note"] == "<p>Keep this note</p>"
    assert marked.field_values()["note"] == ""
    assert annotation.parent_id == original.id


async def test_identical_pdfs_move_annotations_notes_and_relations(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    kept = await attachment(session, library, master, tmp_path, note="<p>Master note</p>")
    removed = await attachment(session, library, other, tmp_path, note="<p>%2Fitems%2FPLACE222</p>")
    # Put the attachment's own key in its embedded note, as annotations do.
    for field in removed.fields:
        if field.field == "note":
            field.value = f"<p>%2Fitems%2F{removed.key}</p>"
    annotation = await factories.make_item(
        session, library, item_type="annotation", parent=removed, deleted=True
    )
    note = await factories.make_item(
        session,
        library,
        item_type="note",
        parent=other,
        fields={"note": f"<p>%2Fitems%2F{other.key} %2Fitems%2F{removed.key}</p>"},
    )
    related = await factories.make_item(session, library)
    await set_relations(session, related, ("dc:relation", items.item_uri(library, removed.key)))
    changed = await merged(session, library, master, [other], tmp_path)

    assert removed.deleted
    assert removed.parent_id == other.id  # the desktop leaves merged PDFs on the trashed duplicate
    assert annotation.parent_id == kept.id
    assert annotation.deleted
    assert removed.field_values().get("note", "") == ""
    assert kept.field_values()["note"] == "<p>Master note</p>"
    assert note.field_values()["note"] == f"<p>%2Fitems%2F{master.key} %2Fitems%2F{kept.key}</p>"
    new_notes = [item for item in changed if item.item_type == "note" and item.id != note.id]
    assert len(new_notes) == 1
    assert new_notes[0].parent_id == master.id
    assert new_notes[0].field_values()["note"] == f"<p>%2Fitems%2F{kept.key}</p>"
    assert relations(kept) == {("dc:replaces", items.item_uri(library, removed.key))}
    assert relations(related) == {("dc:relation", items.item_uri(library, kept.key))}
    assert {item.version for item in changed} == {library.version}
    assert len(changed) == len({item.id for item in changed})
    assert kept.registered_md5 is not None
    assert storage.file_path(tmp_path, kept.registered_md5).read_bytes() == pdf_bytes()


async def test_pdf_text_match_without_a_fulltext_cache(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(session, library, master, tmp_path)
    second = await attachment(
        session, library, other, tmp_path, body=pdf_bytes(" ".join(TEXT.split()[::-1]))
    )
    assert first.registered_md5 != second.registered_md5
    await merged(session, library, master, [other], tmp_path)
    assert not first.deleted
    assert second.deleted


@pytest.mark.parametrize(
    ("master_markup", "other_markup"), [(False, False), (True, False), (False, True), (True, True)]
)
async def test_embedded_markup_decides_which_pdf_survives(
    session: AsyncSession, library: Library, tmp_path: Path, master_markup: bool, other_markup: bool
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(
        session,
        library,
        master,
        tmp_path,
        body=pdf_bytes(subtype="/Ink" if master_markup else None),
    )
    second = await attachment(
        session, library, other, tmp_path, body=pdf_bytes(subtype="/Text" if other_markup else None)
    )
    await merged(session, library, master, [other], tmp_path)
    assert first.deleted == (other_markup and not master_markup)
    assert second.deleted == (not other_markup)
    if not second.deleted:
        assert second.parent_id == master.id


async def test_at_most_one_match_per_duplicate_but_each_duplicate_can_match(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other, third = [await factories.make_item(session, library) for _ in range(3)]
    kept = await attachment(session, library, master, tmp_path)
    first = await attachment(session, library, other, tmp_path)
    extra = await attachment(session, library, other, tmp_path)
    last = await attachment(session, library, third, tmp_path)
    await merged(session, library, master, [other, third], tmp_path)
    assert first.deleted
    assert not extra.deleted
    assert extra.parent_id == master.id
    assert last.deleted
    assert relations(kept) == {
        ("dc:replaces", items.item_uri(library, item.key)) for item in (first, last)
    }


@pytest.mark.parametrize("mode", ["imported_url", "linked_url"])
async def test_web_attachments_match_url_then_title_and_match_only_once(
    session: AsyncSession, library: Library, tmp_path: Path, mode: str
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(
        session, library, master, tmp_path, mode=mode, content_type="text/html", body=b"first"
    )
    exact = await attachment(
        session,
        library,
        master,
        tmp_path,
        mode=mode,
        content_type="text/html",
        body=b"second",
        url="https://example.org/exact",
    )
    second = await attachment(
        session,
        library,
        other,
        tmp_path,
        mode=mode,
        content_type="text/html",
        body=b"third",
        url="https://example.org/exact",
    )
    fallback = await attachment(
        session,
        library,
        other,
        tmp_path,
        mode=mode,
        content_type="text/html",
        body=b"fourth",
        url="https://different.example/",
    )
    unmatched = await attachment(
        session, library, other, tmp_path, mode=mode, content_type="text/html", body=b"last"
    )
    await merged(session, library, master, [other], tmp_path)
    assert second.deleted
    assert fallback.deleted
    assert relations(exact) == {("dc:replaces", items.item_uri(library, second.key))}
    assert relations(first) == {("dc:replaces", items.item_uri(library, fallback.key))}
    assert not unmatched.deleted
    assert unmatched.parent_id == master.id


async def test_annotation_permissions_are_checked_before_any_changes(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    await factories.make_user(session, user_id=2, username="grace")
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(session, library, master, tmp_path)
    second = await attachment(session, library, other, tmp_path)
    annotation = await factories.make_item(session, library, item_type="annotation", parent=second)
    for item in (master, other, first, second):
        item.created_by_user_id = 1
    annotation.created_by_user_id = 2
    await session.commit()
    permit = Access(read=True, write=True, permission="own", user_id=1)
    with pytest.raises(ForbiddenError):
        await merge.merge_items(
            session, library, master, [other], 11, storage_root=tmp_path, permit=permit
        )
    assert not other.deleted
    assert not second.deleted
    assert annotation.parent_id == second.id
    assert {item.version for item in await session.scalars(select(Item))} == {1}
