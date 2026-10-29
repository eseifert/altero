"""State transitions and unavailable-file cases in duplicate attachment merging."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import FullText, Library
from altero.services import storage
from altero.services.auth import Access
from tests import factories
from tests.test_merge import library as library
from tests.test_merge_attachments import attachment, merged
from tests.test_pdfmerge import TEXT, pdf_bytes


async def test_synced_fulltext_cache_is_used_as_on_the_desktop(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(session, library, master, tmp_path)
    second = await attachment(session, library, other, tmp_path, body=pdf_bytes("short text"))
    for item in (first, second):
        session.add(FullText(item_id=item.id, library_id=library.id, content=TEXT, version=1))
    await session.commit()
    await merged(session, library, master, [other], tmp_path)
    assert second.deleted


async def test_insufficient_text_does_not_merge_different_byte_streams(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    body = pdf_bytes("short text")
    await attachment(session, library, master, tmp_path, body=body)
    second = await attachment(session, library, other, tmp_path, body=body + b"\n")
    await merged(session, library, master, [other], tmp_path)
    assert not second.deleted
    assert second.parent_id == master.id


async def test_pdf_imported_file_and_imported_url_can_merge(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    await attachment(session, library, master, tmp_path)
    second = await attachment(session, library, other, tmp_path, mode="imported_url")
    await merged(session, library, master, [other], tmp_path)
    assert second.deleted
    # The subsequent web-attachment step also moves this trashed imported_url.
    assert second.parent_id == master.id


async def test_master_web_pdf_is_a_web_attachment_candidate_too(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    await attachment(session, library, master, tmp_path, mode="imported_url")
    second = await attachment(
        session,
        library,
        other,
        tmp_path,
        mode="imported_url",
        content_type="text/html",
        body=b"page",
    )
    await merged(session, library, master, [other], tmp_path)
    assert second.deleted


async def test_promoted_note_on_an_already_moved_pdf_stays_on_the_master(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other, third = [await factories.make_item(session, library) for _ in range(3)]
    await attachment(session, library, other, tmp_path, note="<p>Keep</p>")
    html = f"<p>%2Fitems%2F{third.key}</p>"
    await attachment(session, library, third, tmp_path, note=html)
    changed = await merged(session, library, master, [other, third], tmp_path)
    note = next(item for item in changed if item.item_type == "note")
    assert note.parent_id == master.id
    # Zotero creates this on the master, so the later moved-notes pass does
    # not replace its citation to the third item.
    assert note.field_values()["note"] == html


async def test_repeated_pdf_swaps_use_the_already_moved_annotation_parent(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other, third = [await factories.make_item(session, library) for _ in range(3)]
    first = await attachment(session, library, master, tmp_path)
    kept = await attachment(session, library, other, tmp_path, body=pdf_bytes(subtype="/Ink"))
    await attachment(session, library, third, tmp_path, body=pdf_bytes(subtype="/Ink"))
    annotation = await factories.make_item(session, library, item_type="annotation", parent=first)
    await merged(session, library, master, [other, third], tmp_path)
    assert annotation.parent_id == kept.id


async def test_missing_master_snapshot_is_not_used_for_deduplication(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    await attachment(
        session,
        library,
        master,
        tmp_path,
        mode="imported_url",
        content_type="text/html",
        registered=False,
    )
    second = await attachment(
        session, library, other, tmp_path, mode="imported_url", content_type="text/html"
    )
    await merged(session, library, master, [other], tmp_path)
    assert not second.deleted
    assert second.parent_id == master.id


@pytest.mark.parametrize("kind", ["different", "unregistered", "missing", "malformed", "encrypted"])
async def test_unmatched_or_unreadable_files_are_retained(
    session: AsyncSession, library: Library, tmp_path: Path, kind: str
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    body = (
        b"not a PDF"
        if kind == "malformed"
        else pdf_bytes(password="secret" if kind == "encrypted" else None)
    )
    first = await attachment(session, library, master, tmp_path, body=body)
    second = await attachment(
        session,
        library,
        other,
        tmp_path,
        body=pdf_bytes(TEXT.replace("alpha", "different")) if kind == "different" else body,
        registered=kind != "unregistered",
    )
    if kind == "missing":
        assert first.registered_md5 is not None
        storage.file_path(tmp_path, first.registered_md5).unlink()
    if kind == "different":
        # A client-provided md5 must never make different bytes match.
        for field in second.fields:
            if field.field == "md5":
                field.value = first.field_values()["md5"]
        await session.commit()
    await merged(session, library, master, [other], tmp_path)
    assert not first.deleted
    assert not second.deleted
    assert second.parent_id == master.id


@pytest.mark.parametrize("deleted_side", ["master", "other"])
async def test_trashed_pdfs_are_moved_but_not_deduplicated(
    session: AsyncSession, library: Library, tmp_path: Path, deleted_side: str
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(session, library, master, tmp_path, deleted=deleted_side == "master")
    second = await attachment(session, library, other, tmp_path, deleted=deleted_side == "other")
    await merged(session, library, master, [other], tmp_path)
    assert first.deleted == (deleted_side == "master")
    assert second.deleted == (deleted_side == "other")
    assert second.parent_id == master.id


@pytest.mark.parametrize("target_has_note", [False, True])
async def test_retaining_the_other_pdf_preserves_both_embedded_notes(
    session: AsyncSession, library: Library, tmp_path: Path, target_has_note: bool
) -> None:
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(session, library, master, tmp_path, note="placeholder")
    second = await attachment(
        session,
        library,
        other,
        tmp_path,
        body=pdf_bytes(subtype="/Ink"),
        note="<p>Keep target</p>" if target_has_note else "",
    )
    html = f"<p>%2Fitems%2F{first.key} %2Fitems%2F{other.key}</p>"
    for field in first.fields:
        if field.field == "note":
            field.value = html
    await session.commit()
    changed = await merged(session, library, master, [other], tmp_path)
    assert first.deleted
    assert not second.deleted
    assert second.parent_id == master.id
    assert first.field_values().get("note", "") == ""
    if target_has_note:
        assert second.field_values()["note"] == "<p>Keep target</p>"
        new_note = next(item for item in changed if item.item_type == "note")
        assert new_note.parent_id == master.id
        assert (
            new_note.field_values()["note"]
            == f"<p>%2Fitems%2F{second.key} %2Fitems%2F{master.key}</p>"
        )
    else:
        assert second.field_values()["note"] == html.replace(first.key, second.key)


async def test_an_unmodified_master_attachment_needs_no_edit_permission(
    session: AsyncSession, library: Library, tmp_path: Path
) -> None:
    await factories.make_user(session, user_id=2, username="grace")
    master, other = [await factories.make_item(session, library) for _ in range(2)]
    first = await attachment(session, library, master, tmp_path)
    second = await attachment(session, library, other, tmp_path)
    untouched = await attachment(
        session, library, master, tmp_path, body=b"image", content_type="image/png"
    )
    for item in (master, other, first, second):
        item.created_by_user_id = 1
    untouched.created_by_user_id = 2
    await session.commit()
    permit = Access(read=True, write=True, permission="own", user_id=1)
    changed = await merged(session, library, master, [other], tmp_path, permit=permit)
    assert second.deleted
    assert untouched.id not in {item.id for item in changed}
    assert untouched.version == 1
