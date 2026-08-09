"""Read one library out of two desktop clients and the server, and diff the three.

`tests/test_sync_cycle.py` replays a captured request sequence and checks that a
second client downloads what the first uploaded. That is not the claim
`docs/motivation.md` makes as success criterion 1, which is about two *installed*
clients converging on a real library. This is the tool for that claim: it reads
each client's `zotero.sqlite` and the server's v3 API, reduces all three to one
canonical shape, and prints every object they disagree about.

Two clients agreeing is not enough on its own -- they could agree on something
the server mangled, each holding its own cached copy -- so the server is read as
a third source and everything is compared against everything.

The readers differ; the shape does not. `_read_client` builds the same
dictionary the API returns as an item's `data`, following the client's own
`Zotero.Item.toJSON`, and `_canonical_item` is then applied to both sides. So a
field this tool has never heard of is still compared: neither reader filters to
a list of known fields.

Usage:

    uv run python tools/compare_libraries.py --key <api key> \\
        A=~/zotero-test/A/data \\
        B=~/zotero-test/B/data \\
        server=http://localhost:8000

A source is a server when it looks like a URL and a client data directory (or a
`zotero.sqlite` itself) otherwise. Quit both clients first: the databases are
opened read-only, and SQLite refuses that on a database with a hot journal
rather than handing back a torn read.

Written against the client's userdata schema 125 (Zotero 9.0.6). It reports
what it read from a schema it does not recognise rather than guessing.
"""

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

#: The client schema this was written against. A higher one is not refused --
#: the tables it reads have been stable for years -- but it is worth saying.
KNOWN_USERDATA_VERSION = 125

#: `itemAttachments.linkMode` as the API spells it.
#: `Zotero.Attachments.LINK_MODE_*` in `chrome/content/zotero/xpcom/attachments.js`.
LINK_MODES = {
    0: "imported_file",
    1: "imported_url",
    2: "linked_file",
    3: "linked_url",
    4: "embedded_image",
}

#: `itemAnnotations.type` as the API spells it.
#: `Zotero.Annotations.ANNOTATION_TYPE_*` in `xpcom/annotations.js`.
ANNOTATION_TYPES = {
    1: "highlight",
    2: "note",
    3: "image",
    4: "ink",
    5: "underline",
    6: "text",
}

#: Only highlights and underlines carry text; `Zotero.Item.toJSON` writes the
#: field for those two types and for no other.
ANNOTATION_TEXT_TYPES = frozenset({"highlight", "underline"})

#: In the item JSON but never synced, so comparing it would report divergence
#: where there is none. `lastRead` is when this installation last opened the
#: file, which is a fact about a computer rather than about the library.
LOCAL_ONLY_FIELDS = frozenset({"lastRead"})


@dataclass(frozen=True)
class LibraryRef:
    """Which library to compare, in the API's own vocabulary."""

    kind: str
    id: int

    @property
    def prefix(self) -> str:
        return f"/users/{self.id}" if self.kind == "user" else f"/groups/{self.id}"

    def __str__(self) -> str:
        return f"{self.kind}/{self.id}"


@dataclass
class Snapshot:
    """One source's answer, canonical and ready to compare."""

    name: str
    origin: str
    version: int
    items: dict[str, dict[str, Any]]
    collections: dict[str, dict[str, Any]]
    searches: dict[str, dict[str, Any]]

    def objects(self, kind: str) -> dict[str, dict[str, Any]]:
        return getattr(self, kind)


class SourceError(Exception):
    """A source could not be read. Reported, never swallowed."""


# --------------------------------------------------------------------------
# Canonical form
# --------------------------------------------------------------------------


def _prune(value: Any) -> Any:
    """Drop what is empty, recursively.

    The two sides disagree about whether an unset value is an empty string or
    an absent key -- the client writes `annotationComment: ''` where the server
    leaves the field out -- and that difference is not divergence. Dropping
    both makes the question unaskable rather than answering it twice.
    """
    if isinstance(value, dict):
        pruned = {name: _prune(inner) for name, inner in value.items()}
        return {name: inner for name, inner in pruned.items() if inner not in ("", None, [], {})}
    if isinstance(value, list):
        return [_prune(inner) for inner in value if inner not in ("", None)]
    return value


def _canonical_item(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce an item's `data` object to what two copies of it must share."""
    item = {
        name: value
        for name, value in data.items()
        if name not in LOCAL_ONLY_FIELDS and name != "key"
    }

    # A tag is `{"tag": name}` or `{"tag": name, "type": 1}`, and the order the
    # two sides list them in is not part of the data.
    item["tags"] = sorted(
        ([tag.get("tag", ""), int(tag.get("type", 0))] for tag in data.get("tags", [])),
    )
    # Same for collection membership, which is a set the API happens to send as
    # an array.
    item["collections"] = sorted(data.get("collections", []))
    # A relation's object is a string when there is one and an array when there
    # are several. One shape is enough to compare.
    item["relations"] = {
        predicate: sorted([objects] if isinstance(objects, str) else objects)
        for predicate, objects in data.get("relations", {}).items()
    }
    # Flags rather than the 1-or-absent the API sends.
    item["deleted"] = bool(data.get("deleted"))
    item["inPublications"] = bool(data.get("inPublications"))

    # Creator order *is* part of the data -- it is the author order -- so the
    # list is left alone and only the empty halves of each name are dropped.
    if "creators" in data:
        item["creators"] = [dict(creator) for creator in data["creators"]]

    # An attachment's modification time is a number of milliseconds whichever
    # side it is read from. It is coerced rather than compared as it arrives
    # because altero currently serves it as a JSON string where
    # api.zotero.org serves a number, and a rig that flagged every stored
    # attachment would say nothing about the library.
    if str(item.get("mtime", "")).lstrip("-").isdigit():
        item["mtime"] = int(item["mtime"])

    return _prune(item)


def _canonical_collection(data: dict[str, Any]) -> dict[str, Any]:
    collection = {name: value for name, value in data.items() if name != "key"}
    # `parentCollection` is a key or `false`; the two spellings of "no parent"
    # are the same fact.
    collection["parentCollection"] = data.get("parentCollection") or None
    collection["deleted"] = bool(data.get("deleted"))
    return _prune(collection)


def _canonical_search(data: dict[str, Any]) -> dict[str, Any]:
    search = {name: value for name, value in data.items() if name != "key"}
    # Conditions are ordered in the client's table by `searchConditionID`, and
    # nothing promises the server hands them back in that order.
    search["conditions"] = sorted(
        (
            [
                condition.get("condition", ""),
                condition.get("operator", ""),
                condition.get("value", ""),
            ]
            for condition in data.get("conditions", [])
        ),
    )
    search["deleted"] = bool(data.get("deleted"))
    return _prune(search)


# --------------------------------------------------------------------------
# The client's database
# --------------------------------------------------------------------------


def _sql_to_iso(value: str | None) -> str | None:
    """`2026-08-09 07:15:00` as the API writes it, `2026-08-09T07:15:00Z`.

    `Zotero.Date.sqlToISO8601`. Anything that does not look like a timestamp is
    handed back untouched rather than guessed at.
    """
    if not value or len(value) != 19 or value[4] != "-" or value[10] != " ":
        return value
    return f"{value[:10]}T{value[11:]}Z"


def _open_client(path: Path) -> sqlite3.Connection:
    database = path / "zotero.sqlite" if path.is_dir() else path
    if not database.exists():
        raise SourceError(f"{database} does not exist")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.execute("select count(*) from version").fetchone()
    except sqlite3.OperationalError as error:
        raise SourceError(
            f"{database} could not be read ({error}). Quit that Zotero instance first: "
            "a database with a hot journal cannot be opened read-only."
        ) from error
    connection.row_factory = sqlite3.Row
    return connection


def _client_library(connection: sqlite3.Connection, library: LibraryRef) -> tuple[int, int]:
    """The client's own id for the library asked for, and its version."""
    if library.kind == "user":
        row = connection.execute(
            "select libraryID, version from libraries where type = 'user'"
        ).fetchone()
        account = connection.execute(
            "select value from settings where setting = 'account' and key = 'userID'"
        ).fetchone()
        if row and account and int(account["value"]) != library.id:
            raise SourceError(
                f"this data directory last synced as user {account['value']}, "
                f"not {library.id}. Comparing it against another account's library "
                "would report divergence that is really two different libraries."
            )
    else:
        row = connection.execute(
            "select l.libraryID, l.version from libraries l "
            "join groups g on g.libraryID = l.libraryID where g.groupID = ?",
            (library.id,),
        ).fetchone()
    if row is None:
        raise SourceError(f"no {library} library in this data directory")
    return int(row["libraryID"]), int(row["version"])


def _client_items(connection: sqlite3.Connection, library_id: int) -> dict[str, dict[str, Any]]:
    """Every item in the library, shaped as the API's `data` object.

    The model is `Zotero.Item.toJSON` in `xpcom/data/item.js`: this builds what
    the client would have uploaded, so that a difference from the server is a
    difference in the data rather than in two ideas of how to write it down.
    """
    keys: dict[int, str] = {}
    items: dict[int, dict[str, Any]] = {}

    for row in connection.execute(
        "select i.itemID, i.key, i.version, t.typeName, i.dateAdded, i.dateModified, "
        "  d.itemID is not null as deleted, p.itemID is not null as inPublications "
        "from items i "
        "join itemTypes t on t.itemTypeID = i.itemTypeID "
        "left join deletedItems d on d.itemID = i.itemID "
        "left join publicationsItems p on p.itemID = i.itemID "
        "where i.libraryID = ?",
        (library_id,),
    ):
        keys[row["itemID"]] = row["key"]
        items[row["itemID"]] = {
            "key": row["key"],
            "version": row["version"],
            "itemType": row["typeName"],
            "dateAdded": _sql_to_iso(row["dateAdded"]),
            "dateModified": _sql_to_iso(row["dateModified"]),
            "deleted": bool(row["deleted"]),
            "inPublications": bool(row["inPublications"]),
            "creators": [],
            "tags": [],
            "collections": [],
            "relations": {},
        }

    for row in connection.execute(
        "select d.itemID, f.fieldName, v.value from itemData d "
        "join items i on i.itemID = d.itemID "
        "join fieldsCombined f on f.fieldID = d.fieldID "
        "join itemDataValues v on v.valueID = d.valueID "
        "where i.libraryID = ?",
        (library_id,),
    ):
        value = row["value"]
        # The one field the client stores as a SQL timestamp and sends as ISO.
        if row["fieldName"] == "accessDate":
            value = _sql_to_iso(str(value))
        items[row["itemID"]][row["fieldName"]] = value

    for row in connection.execute(
        "select ic.itemID, ct.creatorType, c.firstName, c.lastName, c.fieldMode "
        "from itemCreators ic "
        "join items i on i.itemID = ic.itemID "
        "join creators c on c.creatorID = ic.creatorID "
        "join creatorTypes ct on ct.creatorTypeID = ic.creatorTypeID "
        "where i.libraryID = ? order by ic.itemID, ic.orderIndex",
        (library_id,),
    ):
        creator: dict[str, Any] = {"creatorType": row["creatorType"]}
        # `fieldMode` 1 is a single-field name -- an institution, mostly --
        # which the API sends as `name` rather than as two halves.
        if row["fieldMode"]:
            creator["name"] = row["lastName"]
        else:
            creator["firstName"] = row["firstName"]
            creator["lastName"] = row["lastName"]
        items[row["itemID"]]["creators"].append(creator)

    for row in connection.execute(
        "select it.itemID, t.name, it.type from itemTags it "
        "join items i on i.itemID = it.itemID "
        "join tags t on t.tagID = it.tagID "
        "where i.libraryID = ?",
        (library_id,),
    ):
        items[row["itemID"]]["tags"].append({"tag": row["name"], "type": row["type"]})

    for row in connection.execute(
        "select ci.itemID, c.key from collectionItems ci "
        "join collections c on c.collectionID = ci.collectionID "
        "where c.libraryID = ?",
        (library_id,),
    ):
        items[row["itemID"]]["collections"].append(row["key"])

    for row in connection.execute(
        "select ir.itemID, p.predicate, ir.object from itemRelations ir "
        "join items i on i.itemID = ir.itemID "
        "join relationPredicates p on p.predicateID = ir.predicateID "
        "where i.libraryID = ?",
        (library_id,),
    ):
        relations = items[row["itemID"]]["relations"]
        relations.setdefault(row["predicate"], []).append(row["object"])

    for row in connection.execute(
        "select n.itemID, n.parentItemID, n.note from itemNotes n "
        "join items i on i.itemID = n.itemID where i.libraryID = ?",
        (library_id,),
    ):
        item = items[row["itemID"]]
        item["note"] = row["note"]
        if row["parentItemID"]:
            item["parentItem"] = keys[row["parentItemID"]]

    for row in connection.execute(
        "select a.itemID, a.parentItemID, a.linkMode, a.contentType, a.path, "
        "  a.storageModTime, a.storageHash, c.charset "
        "from itemAttachments a "
        "join items i on i.itemID = a.itemID "
        "left join charsets c on c.charsetID = a.charsetID "
        "where i.libraryID = ?",
        (library_id,),
    ):
        item = items[row["itemID"]]
        link_mode = row["linkMode"]
        item["linkMode"] = LINK_MODES.get(link_mode, link_mode)
        item["contentType"] = row["contentType"]
        item["charset"] = row["charset"]
        if row["parentItemID"]:
            item["parentItem"] = keys[row["parentItemID"]]
        path = row["path"] or ""
        if link_mode == 2:
            item["path"] = path
        elif link_mode != 3:
            item["filename"] = path.removeprefix("storage:")
        # `mtime` and `md5` are the *synced* storage properties, and a null one
        # is left out rather than sent -- clearing it would drop the server's
        # idea of which file belongs to the attachment.
        if link_mode in (0, 1):
            if row["storageModTime"] is not None:
                item["mtime"] = row["storageModTime"]
            if row["storageHash"] is not None:
                item["md5"] = row["storageHash"]

    for row in connection.execute(
        "select a.itemID, a.parentItemID, a.type, a.authorName, a.text, a.comment, "
        "  a.color, a.pageLabel, a.sortIndex, a.position, a.isExternal "
        "from itemAnnotations a "
        "join items i on i.itemID = a.itemID where i.libraryID = ?",
        (library_id,),
    ):
        # Annotations read out of the PDF itself are never uploaded --
        # `getUnsynced` in `xpcom/sync/syncLocal.js` excludes them by name --
        # so counting them would report the client as ahead of the server.
        if row["isExternal"]:
            del items[row["itemID"]]
            continue
        item = items[row["itemID"]]
        annotation_type = ANNOTATION_TYPES.get(row["type"], row["type"])
        item["parentItem"] = keys[row["parentItemID"]]
        item["annotationType"] = annotation_type
        item["annotationAuthorName"] = row["authorName"]
        if annotation_type in ANNOTATION_TEXT_TYPES:
            item["annotationText"] = row["text"]
        item["annotationComment"] = row["comment"]
        item["annotationColor"] = row["color"]
        item["annotationPageLabel"] = row["pageLabel"]
        item["annotationSortIndex"] = row["sortIndex"]
        item["annotationPosition"] = row["position"]

    return {item["key"]: _canonical_item(item) for item in items.values()}


def _client_collections(
    connection: sqlite3.Connection, library_id: int
) -> dict[str, dict[str, Any]]:
    parents = {
        row["collectionID"]: row["key"]
        for row in connection.execute(
            "select collectionID, key from collections where libraryID = ?", (library_id,)
        )
    }
    collections = {}
    for row in connection.execute(
        "select c.collectionID, c.key, c.version, c.collectionName, c.parentCollectionID, "
        "  d.collectionID is not null as deleted "
        "from collections c "
        "left join deletedCollections d on d.collectionID = c.collectionID "
        "where c.libraryID = ?",
        (library_id,),
    ):
        collections[row["key"]] = _canonical_collection(
            {
                "key": row["key"],
                "version": row["version"],
                "name": row["collectionName"],
                "parentCollection": parents.get(row["parentCollectionID"]),
                "deleted": bool(row["deleted"]),
            }
        )
    return collections


def _client_searches(connection: sqlite3.Connection, library_id: int) -> dict[str, dict[str, Any]]:
    searches: dict[int, dict[str, Any]] = {}
    identifiers: dict[int, str] = {}
    for row in connection.execute(
        "select savedSearchID, key, version, savedSearchName from savedSearches "
        "where libraryID = ?",
        (library_id,),
    ):
        identifiers[row["savedSearchID"]] = row["key"]
        searches[row["savedSearchID"]] = {
            "key": row["key"],
            "version": row["version"],
            "name": row["savedSearchName"],
            "conditions": [],
        }
    for row in connection.execute(
        "select c.savedSearchID, c.condition, c.operator, c.value "
        "from savedSearchConditions c "
        "join savedSearches s on s.savedSearchID = c.savedSearchID "
        "where s.libraryID = ? order by c.savedSearchID, c.searchConditionID",
        (library_id,),
    ):
        searches[row["savedSearchID"]]["conditions"].append(
            {
                "condition": row["condition"],
                "operator": row["operator"],
                "value": row["value"],
            }
        )
    return {
        identifiers[identifier]: _canonical_search(search)
        for identifier, search in searches.items()
    }


def _read_client(name: str, origin: str, library: LibraryRef) -> Snapshot:
    connection = _open_client(Path(origin).expanduser())
    try:
        schema = connection.execute(
            "select version from version where schema = 'userdata'"
        ).fetchone()
        if schema and schema["version"] != KNOWN_USERDATA_VERSION:
            print(
                f"note: {name} is at userdata schema {schema['version']}, "
                f"and this tool was written against {KNOWN_USERDATA_VERSION}.",
                file=sys.stderr,
            )
        library_id, version = _client_library(connection, library)
        return Snapshot(
            name=name,
            origin=origin,
            version=version,
            items=_client_items(connection, library_id),
            collections=_client_collections(connection, library_id),
            searches=_client_searches(connection, library_id),
        )
    finally:
        connection.close()


# --------------------------------------------------------------------------
# The server's API
# --------------------------------------------------------------------------


def _paged(client: httpx.Client, path: str, **params: Any) -> Iterator[dict[str, Any]]:
    start, limit = 0, 100
    while True:
        response = client.get(
            path, params={"format": "json", "limit": limit, "start": start} | params
        )
        response.raise_for_status()
        page = response.json()
        yield from page
        if len(page) < limit:
            return
        start += limit


def _read_server(name: str, origin: str, library: LibraryRef, key: str) -> Snapshot:
    if not key:
        raise SourceError("reading the server needs --key (or ALTERO_API_KEY)")
    with httpx.Client(
        base_url=origin.rstrip("/"),
        headers={"Zotero-API-Key": key, "Zotero-API-Version": "3"},
        timeout=60.0,
    ) as client:
        # One item, for the header alone. `format=versions` would carry the
        # whole key-to-version map: it is unpaginated, and `limit` on it means
        # nothing (see compatibility.md).
        probe = client.get(f"{library.prefix}/items", params={"format": "json", "limit": 1})
        if probe.status_code == 403:
            raise SourceError(f"{origin} refused the key for {library}")
        probe.raise_for_status()
        version = int(probe.headers.get("Last-Modified-Version", 0))

        # `includeTrashed=1` is what the client itself asks for: an item in the
        # trash is still an item, and a client that has it while the server does
        # not is exactly the divergence being looked for.
        items = {
            entry["key"]: _canonical_item(entry["data"])
            for entry in _paged(client, f"{library.prefix}/items", includeTrashed=1)
        }
        collections = {
            entry["key"]: _canonical_collection(entry["data"])
            for entry in _paged(client, f"{library.prefix}/collections")
        }
        searches = {
            entry["key"]: _canonical_search(entry["data"])
            for entry in _paged(client, f"{library.prefix}/searches")
        }
    return Snapshot(
        name=name,
        origin=origin,
        version=version,
        items=items,
        collections=collections,
        searches=searches,
    )


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------

MISSING = object()


def _shorten(value: Any, width: int = 60) -> str:
    # JSON rather than `str`, so that a difference of type is visible: `"5"`
    # and `5` are two values, and printed bare they would read as one.
    text = json.dumps(value, sort_keys=True, default=str)
    text = text.replace("\n", "\\n")
    return text if len(text) <= width else text[: width - 1] + "…"


def _differences(snapshots: Sequence[Snapshot], kind: str) -> list[str]:
    """Every object the sources do not agree on, one report line each."""
    report: list[str] = []
    keys = sorted({key for snapshot in snapshots for key in snapshot.objects(kind)})
    for key in keys:
        found = [snapshot.objects(kind).get(key) for snapshot in snapshots]
        if all(one == found[0] for one in found[1:]):
            continue
        present = [snapshot.name for snapshot, one in zip(snapshots, found, strict=True) if one]
        absent = [snapshot.name for snapshot, one in zip(snapshots, found, strict=True) if not one]
        if absent:
            report.append(
                f"  {key}  in {', '.join(present) or 'nothing'}; not in {', '.join(absent)}"
            )
            continue
        fields = sorted({field for one in found if one for field in one})
        for field in fields:
            values = [one.get(field, MISSING) if one else MISSING for one in found]
            if all(value == values[0] for value in values[1:]):
                continue
            shown = " ".join(
                f"{snapshot.name}={'—' if value is MISSING else _shorten(value)}"
                for snapshot, value in zip(snapshots, values, strict=True)
            )
            report.append(f"  {key}  {field}  {shown}")
    return report


def _report(snapshots: Sequence[Snapshot], ignore_versions: bool) -> int:
    if ignore_versions:
        for snapshot in snapshots:
            for kind in ("items", "collections", "searches"):
                for canonical in snapshot.objects(kind).values():
                    canonical.pop("version", None)

    width = max(len(snapshot.name) for snapshot in snapshots)
    print(f"{'source':<{width}}  {'items':>7} {'collections':>12} {'searches':>9} {'version':>8}")
    for snapshot in snapshots:
        print(
            f"{snapshot.name:<{width}}  {len(snapshot.items):>7} {len(snapshot.collections):>12} "
            f"{len(snapshot.searches):>9} {snapshot.version:>8}"
        )
    print()

    divergences = 0
    if len({snapshot.version for snapshot in snapshots}) > 1 and not ignore_versions:
        print("library version: the sources are at different versions")
        print("  a client below the server has not finished syncing; one above it has")
        print()
        divergences += 1

    for kind in ("items", "collections", "searches"):
        lines = _differences(snapshots, kind)
        if lines:
            divergences += len(lines)
            print(f"{kind} ({len(lines)}):")
            print("\n".join(lines))
            print()

    if divergences:
        print(f"{divergences} divergences.")
        return 1
    print("No divergence: every source holds the same library.")
    return 0


def _parse_library(value: str) -> LibraryRef:
    kind, _, identifier = value.partition("/")
    if kind not in ("user", "group") or not identifier.isdigit():
        raise argparse.ArgumentTypeError("a library is 'user/<id>' or 'group/<id>'")
    return LibraryRef(kind=kind, id=int(identifier))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare a library across two Zotero clients and the server.",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        metavar="name=source",
        help="a client data directory or zotero.sqlite, or a server's base URL",
    )
    parser.add_argument(
        "--library",
        type=_parse_library,
        default=LibraryRef("user", 1),
        help="which library to compare (default: user/1)",
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("ALTERO_API_KEY", ""),
        help="the API key to read the server with (default: $ALTERO_API_KEY)",
    )
    parser.add_argument(
        "--ignore-versions",
        action="store_true",
        help="compare the data alone, not the version each object is at",
    )
    args = parser.parse_args(argv)

    snapshots: list[Snapshot] = []
    failed = False
    for source in args.sources:
        name, named, origin = source.partition("=")
        if not named:
            # Unnamed sources are allowed, and the column heading is then the
            # host or the directory the source was read from.
            origin, name = name, httpx.URL(name).host or Path(name).name
        try:
            if origin.startswith(("http://", "https://")):
                snapshots.append(_read_server(name, origin, args.library, args.key))
            else:
                snapshots.append(_read_client(name, origin, args.library))
        except (SourceError, httpx.HTTPError) as error:
            print(f"{name}: {error}", file=sys.stderr)
            failed = True

    if failed or len(snapshots) < 2:
        print("Nothing was compared: at least two readable sources are needed.", file=sys.stderr)
        return 2
    return _report(snapshots, args.ignore_versions)


if __name__ == "__main__":
    raise SystemExit(main())
