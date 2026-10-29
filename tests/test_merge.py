"""Duplicate merge graph rules from Zotero 10.0.6's ``mergeItems.mjs``.

Attachment deduplication has its own rules; these tests cover the enclosing
transaction and ``moveRelations``, including repeated merges and permissions.
"""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.models import Item, ItemRelation, Library, LibraryType
from altero.services import items, itemwrites, merge, writes
from altero.services.auth import Access, get_library
from tests import factories


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await factories.make_user(session)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


async def run_merge(
    session: AsyncSession,
    library: Library,
    master: Item,
    others: list[Item],
    *,
    permit: Access | None = None,
) -> list[Item]:
    await writes.lock_library(session, library)
    version = await writes.bump_library_version(session, library)
    changed = await merge.merge_items(session, library, master, others, version, permit=permit)
    await session.commit()
    return changed


def relations(item: Item) -> set[tuple[str, str]]:
    return {(relation.predicate, relation.object) for relation in item.relations}


async def set_relations(session: AsyncSession, item: Item, *values: tuple[str, str]) -> None:
    item.relations = [ItemRelation(predicate=pred, object=obj) for pred, obj in values]
    await session.commit()


async def test_merge_keeps_master_fields_and_creators_and_earliest_date(
    session: AsyncSession, library: Library
) -> None:
    master = await factories.make_item(
        session, library, fields={"title": "Keep me"}, creators=[("author", "Ada", "Lovelace")]
    )
    older = await factories.make_item(session, library, fields={"title": "Other"})
    newest = await factories.make_item(session, library)
    master.date_added = datetime(2020, 1, 1)
    older.date_added = datetime(1990, 1, 1)
    newest.date_added = datetime(2024, 1, 1)
    await session.commit()
    before = library.version

    changed = await run_merge(session, library, master, [older, newest])

    assert master.field_values() == {"title": "Keep me"}
    assert master.creators[0].last_name == "Lovelace"
    assert master.date_added == datetime(1990, 1, 1)
    assert not master.deleted
    assert older.deleted
    assert newest.deleted
    assert library.version == before + 1
    assert {item.id for item in changed} == {master.id, older.id, newest.id}
    assert {item.version for item in changed} == {library.version}
    assert relations(master) == {
        ("dc:replaces", items.item_uri(library, older.key)),
        ("dc:replaces", items.item_uri(library, newest.key)),
    }
    # Trashing is not an outright deletion: sync must fetch the duplicate.
    assert await session.get(Item, older.id) is older


async def test_children_move_including_trash_without_changing_files_or_grandchildren(
    session: AsyncSession, library: Library
) -> None:
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    existing = await factories.make_item(session, library, item_type="note", parent=master)
    note = await factories.make_item(
        session,
        library,
        item_type="note",
        parent=other,
        deleted=True,
        fields={"note": "<p>Old</p>"},
    )
    file = await factories.make_item(
        session,
        library,
        item_type="attachment",
        parent=other,
        fields={
            "linkMode": "imported_file",
            "filename": "file.pdf",
            "md5": "a" * 32,
            "mtime": "42",
        },
    )
    annotation = await factories.make_item(session, library, item_type="annotation", parent=file)
    file_fields = file.field_values()
    changed = await run_merge(session, library, master, [other])

    assert note.parent_id == master.id
    assert note.deleted
    assert file.parent_id == master.id
    assert not file.deleted
    assert file.field_values() == file_fields
    assert file.registered_md5 == "a" * 32
    assert annotation.parent_id == file.id
    assert existing.version == annotation.version == 1
    assert {item.id for item in changed} == {master.id, other.id, note.id, file.id}
    assert {item.version for item in changed} == {library.version}


async def test_note_key_rewrite_matches_desktop_scope_and_first_attachment_attribute(
    session: AsyncSession, library: Library
) -> None:
    master = await factories.make_item(session, library, key="MASTER22")
    other = await factories.make_item(session, library, key="OTHER222")
    html = (
        '<p data-citation="%2Fitems%2FOTHER222 %2Fitems%2FOTHER222">OTHER222</p>'
        '<img data-attachment-key="OTHER222"><img data-attachment-key="OTHER222">'
        '<a href="http://zotero.org/users/1/items/OTHER222">link</a>'
    )
    note = await factories.make_item(
        session, library, item_type="note", parent=other, fields={"note": html}
    )
    await run_merge(session, library, master, [other])

    assert note.field_values()["note"] == (
        '<p data-citation="%2Fitems%2FMASTER22 %2Fitems%2FMASTER22">OTHER222</p>'
        '<img data-attachment-key="MASTER22"><img data-attachment-key="OTHER222">'
        '<a href="http://zotero.org/users/1/items/OTHER222">link</a>'
    )


async def test_tags_combine_with_manual_winning_and_collections_are_unioned(
    session: AsyncSession, library: Library
) -> None:
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    first = await factories.make_collection(session, library, items=[master, other])
    second = await factories.make_collection(session, library, items=[other])
    await itemwrites.save_item(
        session,
        library,
        {"tags": [{"tag": "automatic", "type": 1}, {"tag": "manual"}]},
        1,
        key=master.key,
        replace=False,
    )
    await itemwrites.save_item(
        session,
        library,
        {"tags": [{"tag": "automatic"}, {"tag": "manual", "type": 1}, {"tag": "new", "type": 1}]},
        1,
        key=other.key,
        replace=False,
    )
    await session.commit()

    await run_merge(session, library, master, [other])

    tags = await items.tags_for(session, [master, other])
    assert sorted(tags[master.id]) == [("automatic", 0), ("manual", 0), ("new", 1)]
    assert sorted(tags[other.id]) == [("automatic", 0), ("manual", 1), ("new", 1)]
    collections = await items.collection_keys_for(session, [master, other])
    assert set(collections[master.id]) == set(collections[other.id]) == {first.key, second.key}


async def test_relations_move_and_incoming_links_change_only_in_same_library(
    session: AsyncSession, library: Library
) -> None:
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    related = await factories.make_item(session, library)
    tracker = await factories.make_item(session, library)
    await factories.make_user(session, user_id=2, username="grace")
    foreign_library = await get_library(session, LibraryType.USER, 2)
    foreign = await factories.make_item(session, foreign_library)
    master_uri, other_uri, related_uri = (
        items.item_uri(library, item.key) for item in (master, other, related)
    )
    replaced_uri = items.item_uri(library, "BEFORE22")
    await set_relations(
        session,
        other,
        ("dc:relation", master_uri),
        ("dc:relation", related_uri),
        ("dc:replaces", replaced_uri),
    )
    await set_relations(session, related, ("dc:relation", other_uri), ("owl:sameAs", other_uri))
    await set_relations(session, tracker, ("dc:replaces", other_uri))
    await set_relations(session, foreign, ("dc:relation", other_uri))

    changed = await run_merge(session, library, master, [other])

    assert relations(master) == {
        ("dc:relation", related_uri),
        ("dc:replaces", replaced_uri),
        ("dc:replaces", other_uri),
    }
    assert relations(other) == {("dc:relation", master_uri), ("dc:relation", related_uri)}
    assert relations(related) == {("dc:relation", master_uri), ("owl:sameAs", master_uri)}
    assert relations(foreign) == {("dc:relation", other_uri)}
    assert relations(tracker) == {("dc:replaces", other_uri)}
    assert foreign.version == tracker.version == 1
    assert {item.id for item in changed} == {master.id, other.id, related.id}


async def test_repeated_merges_transfer_tracking_without_two_subjects(
    session: AsyncSession, library: Library
) -> None:
    master, other, oldest = [await factories.make_item(session, library) for _ in range(3)]
    await run_merge(session, library, other, [oldest])
    await run_merge(session, library, master, [other])

    assert relations(master) == {
        ("dc:replaces", items.item_uri(library, item.key)) for item in (other, oldest)
    }
    assert not relations(other)


async def test_multiple_duplicates_and_a_moved_note_can_also_have_incoming_relations(
    session: AsyncSession, library: Library
) -> None:
    master, first, second = [await factories.make_item(session, library) for _ in range(3)]
    note = await factories.make_item(session, library, item_type="note", parent=first)
    first_uri, second_uri, master_uri = (
        items.item_uri(library, item.key) for item in (first, second, master)
    )
    await set_relations(session, first, ("dc:relation", second_uri))
    await set_relations(session, note, ("dc:relation", first_uri), ("dc:relation", second_uri))

    changed = await run_merge(session, library, master, [first, second])

    assert relations(first) == relations(note) == {("dc:relation", master_uri)}
    assert note.parent_id == master.id
    assert len(changed) == len({item.id for item in changed}) == 4
    assert {item.version for item in changed} == {library.version}


async def test_group_author_of_every_changed_item_is_recorded(
    session: AsyncSession, library: Library
) -> None:
    group = await factories.make_group(session, owner_id=1)
    master = await factories.make_item(session, group)
    other = await factories.make_item(session, group)
    note = await factories.make_item(session, group, item_type="note", parent=other)
    for item in (master, other, note):
        item.created_by_user_id = 1
    await session.commit()
    permit = Access(read=True, write=True, permission="own", user_id=1)

    await writes.lock_library(session, group)
    version = await writes.bump_library_version(session, group)
    changed = await merge.merge_items(
        session, group, master, [other], version, actor_id=1, permit=permit
    )
    await session.commit()

    assert {item.id for item in changed} == {master.id, other.id, note.id}
    assert {item.created_by_user_id for item in changed} == {1}
    assert {item.last_modified_by_user_id for item in changed} == {1}
    assert relations(master) == {("dc:replaces", items.item_uri(group, other.key))}


@pytest.mark.parametrize(
    "invalid", ["empty", "self", "repeated", "foreign", "note", "trash", "type"]
)
async def test_invalid_merge_is_refused_before_any_item_changes(
    session: AsyncSession, library: Library, invalid: str
) -> None:
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    others = [other]
    if invalid == "empty":
        others = []
    elif invalid == "self":
        others = [master]
    elif invalid == "repeated":
        others = [other, other]
    elif invalid == "foreign":
        other.library_id += 99
    elif invalid == "note":
        other.item_type = "note"
    elif invalid == "trash":
        other.deleted = True
    elif invalid == "type":
        other.item_type = "journalArticle"
    with session.no_autoflush, pytest.raises(InvalidInputError):
        await merge.merge_items(session, library, master, others, 2)
    assert not master.deleted
    assert master.version == 1
    assert other.version == 1


@pytest.mark.parametrize(
    "denied", ["read", "add", "master", "other", "child", "incoming", "confined", "notes"]
)
async def test_every_affected_item_is_checked_before_writing(
    session: AsyncSession, library: Library, denied: str
) -> None:
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    child = await factories.make_item(session, library, item_type="note", parent=other)
    incoming = await factories.make_item(session, library)
    await set_relations(session, incoming, ("dc:relation", items.item_uri(library, other.key)))
    for item in (master, other, child, incoming):
        item.created_by_user_id = 1
    access = Access(read=True, write=True, permission="own", user_id=1)
    if denied == "read":
        access = Access(read=True, write=False)
    elif denied == "add":
        access = Access(read=True, write=True, permission="add")
    elif denied == "confined":
        access = Access(read=True, write=True, collections=frozenset())
    elif denied == "notes":
        access = Access(read=True, write=True, notes=False)
    else:
        {"master": master, "other": other, "child": child, "incoming": incoming}[
            denied
        ].created_by_user_id = None
    # Do not flush fake authors (this fixture has no second account).
    with session.no_autoflush, pytest.raises(ForbiddenError):
        await merge.merge_items(session, library, master, [other], 2, permit=access)
    assert master.version == other.version == child.version == incoming.version == 1
    assert child.parent_id == other.id
    assert not other.deleted


async def test_rollback_restores_graph_and_library_version(
    session: AsyncSession, library: Library
) -> None:
    master = await factories.make_item(session, library)
    other = await factories.make_item(session, library)
    note = await factories.make_item(session, library, item_type="note", parent=other)
    before, library_id, master_id, other_id, note_id = (
        library.version,
        library.id,
        master.id,
        other.id,
        note.id,
    )
    await writes.lock_library(session, library)
    version = await writes.bump_library_version(session, library)
    await merge.merge_items(session, library, master, [other], version)
    await session.rollback()

    stored = {item.id: item for item in await session.scalars(select(Item))}
    assert not stored[other_id].deleted
    assert stored[note_id].parent_id == other_id
    assert not relations(stored[master_id])
    stored_library = await session.get(Library, library_id)
    assert stored_library is not None
    assert stored_library.version == before
