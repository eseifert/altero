"""The client reader and the API reader have to agree about what an item is.

`tools/compare_libraries.py` reports divergence between two desktop clients and
the server. It is only worth trusting if its two readers -- one over the
client's SQLite, one over the v3 API -- reduce the same item to the same thing.
Where they do not, it would report divergence that is really a difference
between two ways of writing an item down, and the manual sync test it exists
for would drown in false alarms.

So the fixture below builds a client database by hand and states, next to it,
the JSON the API returns for the same library. The test is that the two are
indistinguishable after canonicalisation.
"""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tools.compare_libraries import (
    LibraryRef,
    Snapshot,
    SourceError,
    _canonical_collection,
    _canonical_item,
    _canonical_search,
    _differences,
    _read_client,
)

#: The tables the reader touches, as the client declares them. Trimmed to the
#: columns it selects: a fuller copy would not test anything more.
SCHEMA = """
create table version (schema text primary key, version int not null);
create table settings (setting text, key text, value);
create table libraries (libraryID integer primary key, type text not null, version int not null);
create table groups (groupID integer primary key, libraryID int not null);
create table itemTypes (itemTypeID integer primary key, typeName text);
create table items (
    itemID integer primary key, itemTypeID int not null, dateAdded timestamp,
    dateModified timestamp, libraryID int not null, key text not null, version int not null
);
create table deletedItems (itemID integer primary key);
create table publicationsItems (itemID integer primary key);
create table fieldsCombined (fieldID integer primary key, fieldName text not null);
create table itemDataValues (valueID integer primary key, value);
create table itemData (itemID int, fieldID int, valueID int);
create table creatorTypes (creatorTypeID integer primary key, creatorType text);
create table creators (
    creatorID integer primary key, firstName text, lastName text, fieldMode int
);
create table itemCreators (
    itemID int not null, creatorID int not null, creatorTypeID int not null, orderIndex int not null
);
create table tags (tagID integer primary key, name text not null);
create table itemTags (itemID int not null, tagID int not null, type int not null);
create table collections (
    collectionID integer primary key, collectionName text not null, parentCollectionID int,
    libraryID int not null, key text not null, version int not null
);
create table deletedCollections (collectionID integer primary key);
create table collectionItems (collectionID int not null, itemID int not null);
create table relationPredicates (predicateID integer primary key, predicate text);
create table itemRelations (itemID int not null, predicateID int not null, object text not null);
create table itemNotes (itemID integer primary key, parentItemID int, note text, title text);
create table charsets (charsetID integer primary key, charset text);
create table itemAttachments (
    itemID integer primary key, parentItemID int, linkMode int, contentType text, charsetID int,
    path text, storageModTime int, storageHash text
);
create table itemAnnotations (
    itemID integer primary key, parentItemID int not null, type integer not null, authorName text,
    text text, comment text, color text, pageLabel text, sortIndex text not null,
    position text not null, isExternal int not null
);
create table savedSearches (
    savedSearchID integer primary key, savedSearchName text not null, libraryID int not null,
    key text not null, version int not null
);
create table savedSearchConditions (
    savedSearchID int not null, searchConditionID int not null, condition text not null,
    operator text, value text
);
"""

#: What the API answers for the library the fixture builds, item for item. The
#: shapes are upstream's: `deleted` is 1 or absent, a tag with no `type` is a
#: manual one, an unset annotation field is an empty string.
API_ITEMS: dict[str, dict[str, Any]] = {
    "AAAAAAAA": {
        "key": "AAAAAAAA",
        "version": 12,
        "itemType": "bookSection",
        "title": "A Chapter",
        "bookTitle": "A Book",
        "accessDate": "2026-08-01T09:00:00Z",
        "creators": [
            {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
            {"creatorType": "editor", "name": "A Committee"},
        ],
        "tags": [{"tag": "unread"}, {"tag": "machine", "type": 1}],
        "collections": ["CCCCCCCC"],
        "relations": {"dc:replaces": "http://zotero.org/users/1/items/ZZZZZZZZ"},
        "dateAdded": "2026-07-01T10:00:00Z",
        "dateModified": "2026-07-02T11:00:00Z",
    },
    "BBBBBBBB": {
        "key": "BBBBBBBB",
        "version": 12,
        "itemType": "note",
        "parentItem": "AAAAAAAA",
        "note": "<p>A note</p>",
        "tags": [],
        "relations": {},
        "dateAdded": "2026-07-01T10:00:00Z",
        "dateModified": "2026-07-02T11:00:00Z",
    },
    "DDDDDDDD": {
        "key": "DDDDDDDD",
        "version": 14,
        "itemType": "attachment",
        "parentItem": "AAAAAAAA",
        "linkMode": "imported_url",
        "title": "Snapshot",
        "contentType": "text/html",
        "charset": "utf-8",
        "filename": "snapshot.html",
        "md5": "d41d8cd98f00b204e9800998ecf8427e",
        # A string, because that is what altero serves today. api.zotero.org
        # sends a number and the client stores an integer.
        "mtime": "1785701798544",
        "tags": [],
        "relations": {},
        "dateAdded": "2026-07-01T10:00:00Z",
        "dateModified": "2026-07-02T11:00:00Z",
    },
    "EEEEEEEE": {
        "key": "EEEEEEEE",
        "version": 15,
        "itemType": "annotation",
        "parentItem": "DDDDDDDD",
        "annotationType": "highlight",
        "annotationText": "a sentence",
        "annotationComment": "",
        "annotationColor": "#ffd400",
        "annotationPageLabel": "3",
        "annotationSortIndex": "00003|000000|00000",
        "annotationPosition": '{"pageIndex":3}',
        "tags": [],
        "relations": {},
        "dateAdded": "2026-07-01T10:00:00Z",
        "dateModified": "2026-07-02T11:00:00Z",
    },
    "FFFFFFFF": {
        "key": "FFFFFFFF",
        "version": 16,
        "itemType": "document",
        "title": "In the trash",
        "deleted": 1,
        "tags": [],
        "collections": [],
        "relations": {},
        "dateAdded": "2026-07-01T10:00:00Z",
        "dateModified": "2026-07-02T11:00:00Z",
    },
}

API_COLLECTIONS: dict[str, dict[str, Any]] = {
    "CCCCCCCC": {
        "key": "CCCCCCCC",
        "version": 11,
        "name": "Reading",
        "parentCollection": False,
        "relations": {},
    },
}

API_SEARCHES: dict[str, dict[str, Any]] = {
    "SSSSSSSS": {
        "key": "SSSSSSSS",
        "version": 13,
        "name": "Unread",
        "conditions": [{"condition": "tag", "operator": "is", "value": "unread"}],
    },
}


def _build_client(path: Path) -> None:
    """Write the same library into a client database."""
    connection = sqlite3.connect(path / "zotero.sqlite")
    connection.executescript(SCHEMA)
    connection.executescript(
        """
        insert into version values ('userdata', 125);
        insert into settings values ('account', 'userID', '1');
        insert into libraries values (1, 'user', 42);

        insert into itemTypes values
            (1, 'bookSection'), (2, 'note'), (3, 'attachment'),
            (4, 'annotation'), (5, 'document');
        insert into fieldsCombined values
            (1, 'title'), (2, 'bookTitle'), (3, 'accessDate');
        insert into itemDataValues values
            (1, 'A Chapter'), (2, 'A Book'), (3, '2026-08-01 09:00:00'),
            (4, 'Snapshot'), (5, 'In the trash');
        insert into creatorTypes values (1, 'author'), (2, 'editor');
        insert into creators values (1, 'Ada', 'Lovelace', 0), (2, '', 'A Committee', 1);
        insert into tags values (1, 'unread'), (2, 'machine');
        insert into relationPredicates values (1, 'dc:replaces');
        insert into charsets values (1, 'utf-8');

        insert into items values
            (1, 1, '2026-07-01 10:00:00', '2026-07-02 11:00:00', 1, 'AAAAAAAA', 12),
            (2, 2, '2026-07-01 10:00:00', '2026-07-02 11:00:00', 1, 'BBBBBBBB', 12),
            (3, 3, '2026-07-01 10:00:00', '2026-07-02 11:00:00', 1, 'DDDDDDDD', 14),
            (4, 4, '2026-07-01 10:00:00', '2026-07-02 11:00:00', 1, 'EEEEEEEE', 15),
            (5, 5, '2026-07-01 10:00:00', '2026-07-02 11:00:00', 1, 'FFFFFFFF', 16),
            (6, 4, '2026-07-01 10:00:00', '2026-07-02 11:00:00', 1, 'GGGGGGGG', 17);
        insert into deletedItems values (5);

        insert into itemData values (1, 1, 1), (1, 2, 2), (1, 3, 3), (3, 1, 4), (5, 1, 5);
        insert into itemCreators values (1, 1, 1, 0), (1, 2, 2, 1);
        insert into itemTags values (1, 1, 0), (1, 2, 1);
        insert into itemRelations values (1, 1, 'http://zotero.org/users/1/items/ZZZZZZZZ');

        insert into collections values (1, 'Reading', null, 1, 'CCCCCCCC', 11);
        insert into collectionItems values (1, 1);

        insert into itemNotes values (2, 1, '<p>A note</p>', 'A note');
        insert into itemAttachments values
            (3, 1, 1, 'text/html', 1, 'storage:snapshot.html', 1785701798544,
             'd41d8cd98f00b204e9800998ecf8427e');
        insert into itemAnnotations values
            (4, 3, 1, '', 'a sentence', '', '#ffd400', '3', '00003|000000|00000',
             '{"pageIndex":3}', 0),
            (6, 3, 1, '', 'from the file itself', '', '#a28ae5', '4', '00004|000000|00000',
             '{"pageIndex":4}', 1);

        insert into savedSearches values (1, 'Unread', 1, 'SSSSSSSS', 13);
        insert into savedSearchConditions values (1, 1, 'tag', 'is', 'unread');
        """
    )
    connection.commit()
    connection.close()


@pytest.fixture
def client_snapshot(tmp_path: Path) -> Snapshot:
    _build_client(tmp_path)
    return _read_client("client", str(tmp_path), LibraryRef("user", 1))


@pytest.fixture
def server_snapshot() -> Snapshot:
    return Snapshot(
        name="server",
        origin="http://localhost:8000",
        version=42,
        items={key: _canonical_item(data) for key, data in API_ITEMS.items()},
        collections={key: _canonical_collection(data) for key, data in API_COLLECTIONS.items()},
        searches={key: _canonical_search(data) for key, data in API_SEARCHES.items()},
    )


class TestTheTwoReadersAgree:
    def test_every_item_reduces_to_the_same_thing(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        assert client_snapshot.items == server_snapshot.items

    def test_collections_and_searches_do_too(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        assert client_snapshot.collections == server_snapshot.collections
        assert client_snapshot.searches == server_snapshot.searches

    def test_the_library_version_is_read(self, client_snapshot: Snapshot) -> None:
        assert client_snapshot.version == 42

    def test_nothing_is_reported_when_they_agree(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        for kind in ("items", "collections", "searches"):
            assert _differences([client_snapshot, server_snapshot], kind) == []

    def test_an_attachment_modification_time_is_a_number_either_way(self) -> None:
        # The one place the two sides are typed differently: the client stores
        # an integer, api.zotero.org sends a number, and altero sends a string.
        # Compared as they arrive, every stored attachment in the library would
        # be reported and the report would be useless.
        assert _canonical_item({"mtime": "1785701798544"})["mtime"] == 1785701798544

    def test_an_external_annotation_is_not_counted(self, client_snapshot: Snapshot) -> None:
        # It lives in the PDF, and `getUnsynced` in the client never uploads
        # it, so a server without it is not behind.
        assert "GGGGGGGG" not in client_snapshot.items


class TestDivergenceIsFound:
    def test_a_changed_field(self, client_snapshot: Snapshot, server_snapshot: Snapshot) -> None:
        server_snapshot.items["AAAAAAAA"]["title"] = "A Different Chapter"

        report = _differences([client_snapshot, server_snapshot], "items")

        assert len(report) == 1
        assert "AAAAAAAA" in report[0]
        assert "title" in report[0]
        assert "A Chapter" in report[0]
        assert "A Different Chapter" in report[0]

    def test_an_item_one_source_has_not_got(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        del server_snapshot.items["DDDDDDDD"]

        report = _differences([client_snapshot, server_snapshot], "items")

        assert len(report) == 1
        assert "DDDDDDDD" in report[0]
        assert "in client; not in server" in report[0]

    def test_an_item_left_in_the_trash_on_one_side(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        # The trash is part of the library: an item restored on one client and
        # still deleted on the other is divergence, not a difference of view.
        server_snapshot.items["FFFFFFFF"].pop("deleted")

        report = _differences([client_snapshot, server_snapshot], "items")

        assert len(report) == 1
        assert "FFFFFFFF" in report[0]
        assert "deleted" in report[0]

    def test_a_version_one_client_has_not_caught_up_with(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        server_snapshot.items["AAAAAAAA"]["version"] = 99

        report = _differences([client_snapshot, server_snapshot], "items")

        assert len(report) == 1
        assert "version" in report[0]

    def test_a_collection_moved_on_one_side(
        self, client_snapshot: Snapshot, server_snapshot: Snapshot
    ) -> None:
        server_snapshot.collections["CCCCCCCC"]["parentCollection"] = "PPPPPPPP"

        report = _differences([client_snapshot, server_snapshot], "collections")

        assert len(report) == 1
        assert "parentCollection" in report[0]


class TestWhatItRefusesToCompare:
    def test_a_data_directory_from_another_account(self, tmp_path: Path) -> None:
        _build_client(tmp_path)

        with pytest.raises(SourceError, match="last synced as user 1"):
            _read_client("client", str(tmp_path), LibraryRef("user", 2))

    def test_a_library_that_is_not_there(self, tmp_path: Path) -> None:
        _build_client(tmp_path)

        with pytest.raises(SourceError, match="no group/5 library"):
            _read_client("client", str(tmp_path), LibraryRef("group", 5))

    def test_a_data_directory_that_is_not_one(self, tmp_path: Path) -> None:
        with pytest.raises(SourceError, match="does not exist"):
            _read_client("client", str(tmp_path), LibraryRef("user", 1))
