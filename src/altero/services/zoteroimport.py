"""Copying a personal library out of zotero.org and into this server.

The whole of it is a fetch and a translation. What arrives is the v3 API's own
JSON, which altero already knows how to read -- ``validate_item`` is the same
check a syncing client's uploads go through -- and what leaves is the archive
``altero library export`` writes. Nothing new writes to the database: the
archive goes through :func:`altero.services.transfer.import_library`, which
already restores a whole library at exact keys and versions and is already
tested for it.

That is the reason for the detour through a file. A migration that wrote rows
of its own would be a second implementation of the one operation on this server
that must not be got wrong, and it would be the implementation nobody had
exercised. Going through the archive also leaves the person with a copy of
their zotero.org library on disk, which is worth having whatever happens next.

**Keys and versions are kept.** An item that was `ABCD2345` at version 412 on
zotero.org is `ABCD2345` at version 412 here, and the library's own version
comes across too. It costs nothing -- the archive format carries all of it --
and it is what makes the copy a copy rather than a re-typing.

**What cannot come across**, because the API does not serve it:

- ``serverDateModified``. Not in any JSON response; the client's own
  ``dateModified`` is used in its place, which is the same instant for
  everything the client itself last wrote.
- Timestamps for collections, searches and tags. The API exposes none, and
  neither does altero's, so they are stamped with the moment of the migration.
- Versions in the deletion log. ``/deleted`` answers with keys and no versions,
  so every entry is recorded at the library's current version -- which is the
  safe direction: a client asking what went since any earlier point is told
  about all of it.

**What is rewritten.** Relation URIs -- ``dc:relation`` between related items,
``owl:sameAs``, the merge tracker's ``dc:replaces`` -- are Zotero object
identifiers of the form ``http://zotero.org/users/<id>/items/<key>``, and the
``<id>`` in them is the zotero.org account's. Where the altero account's number
differs, they are rewritten to it, or every related-items link in the library
would point at a user this server has never heard of.

The host in them stays ``zotero.org``, and that is deliberate. It is a
namespace, not an address: nothing fetches it, and the desktop client's parser
is anchored to the literal string (``Zotero.URI.defaultPrefix``, a hard-coded
``http://zotero.org/``), so a URI naming this server instead would stop
matching and take related items, merged-item tracking and `owl:sameAs` with it.
The links that *are* links -- ``self``, ``up``, the attachment URLs -- are built
by this server's own serialiser and already name it; nothing of zotero.org's
survives in them. Attachment bytes are downloaded into the file store, so no
address at their storage provider is kept either.
"""

import json
import logging
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from altero import __version__
from altero.errors import InvalidInputError
from altero.keys import generate_key
from altero.models import ItemCreator, LibraryType
from altero.services import itemdata
from altero.services.itemwrites import validate_item
from altero.services.storage import file_digest
from altero.services.transfer import FILE_PREFIX, FORMAT_VERSION, MANIFEST
from altero.services.zoteroapi import ZoteroApi, ZoteroApiError

logger = logging.getLogger("altero.zoteroimport")

#: Attachment link modes whose bytes live on the server. A linked file or URL
#: was never uploaded, so asking for it is a wasted request and a 404.
STORED_LINK_MODES = frozenset({"imported_file", "imported_url"})


@dataclass
class Progress:
    """Where a migration has got to, for anything watching it."""

    stage: str
    done: int = 0
    total: int | None = None
    detail: str = ""


#: Called as a migration proceeds. Never required: the command line prints
#: these, the browser polls them, and a test ignores them.
Report = Callable[[Progress], None]


@dataclass
class Summary:
    """What a migration found and what it could not bring across."""

    user_id: int = 0
    username: str = ""
    library_version: int = 0
    items: int = 0
    collections: int = 0
    searches: int = 0
    tags: int = 0
    settings: int = 0
    fulltext: int = 0
    deleted: int = 0
    files: int = 0
    #: Attachments whose bytes zotero.org would not serve -- most often because
    #: the account had no storage left, or never uploaded them.
    files_missing: list[str] = field(default_factory=list)
    #: Items this server could not store, with the reason. An item type or
    #: field newer than the vendored schema lands here rather than stopping the
    #: whole migration.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    #: Relation URIs pointed at the new account's number.
    rewritten: int = 0
    #: Parts of the library zotero.org would not serve, named in English. The
    #: copy is missing them and is otherwise whole.
    unavailable: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.skipped and not self.files_missing and not self.unavailable


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0).isoformat(sep=" ")


def _rewriter(old_id: int, new_id: int) -> Callable[[str], str]:
    """Return a function that points object URIs at the new account.

    Only the account's own URIs are touched. One naming a *group* is left as it
    is: this migration does not bring groups across, so rewriting it would aim
    a dangling reference at a group of this server's that is not the same
    group. Dangling either way, and less misleading pointing at its origin.
    """
    if old_id == new_id:
        return lambda value: value

    pattern = re.compile(rf"^(http://zotero\.org/users/){old_id}(?=/|$)")
    return lambda value: pattern.sub(rf"\g<1>{new_id}", value)


class _Assembler:
    """Builds the archive documents as pages arrive."""

    def __init__(self, rewrite: Callable[[str], str]) -> None:
        self.rewrite = rewrite
        self.items: list[dict[str, Any]] = []
        self.summary = Summary()
        #: (name, type) -> the keys of the items carrying it. Built from the
        #: items rather than from `/tags`, which cannot say which items a tag
        #: is on; a tag exists only through them anyway.
        self.tags: dict[tuple[str, int], list[str]] = {}
        #: collection key -> item keys, taken from each item's `collections`.
        self.membership: dict[str, list[str]] = {}
        #: Attachment keys with the digest of the file they claim.
        self.files: list[tuple[str, str]] = []

    def add_item(self, envelope: dict[str, Any]) -> None:
        data = envelope.get("data") or {}
        key = str(data.get("key") or envelope.get("key") or "")

        try:
            parsed = validate_item(data, None, LibraryType.USER)
        except InvalidInputError as thrown:
            self.summary.skipped.append((key, str(thrown)))
            logger.warning("skipping item %s: %s", key, thrown)
            return

        creators = [
            ItemCreator(
                position=index,
                creator_type=creator["creatorType"],
                first_name=creator.get("firstName"),
                last_name=creator.get("lastName"),
                name=creator.get("name"),
            )
            for index, creator in enumerate(parsed["creators"])
        ]
        fields: dict[str, str] = parsed["fields"]
        item_type = parsed["item_type"]

        # The client's own timestamp stands in for the server's, which no
        # response carries. Both are the moment the client last wrote.
        modified = parsed["date_modified"] or datetime.now(UTC).replace(tzinfo=None)
        added = parsed["date_added"] or modified

        relations = []
        for predicate, obj in parsed["relations"]:
            pointed = self.rewrite(obj)
            if pointed != obj:
                self.summary.rewritten += 1
            relations.append({"predicate": predicate, "object": pointed})

        self.items.append(
            {
                "key": key,
                "version": int(envelope.get("version") or data.get("version") or 0),
                "itemType": item_type,
                "parent": parsed["parent_item"],
                # Absent from `parsed` unless the envelope named them, which is
                # how a patch says "leave it alone"; here every item is new, so
                # not mentioned is not set.
                "deleted": parsed.get("deleted", False),
                "inPublications": parsed.get("in_publications", False),
                "sortTitle": itemdata.derive_sort_title(item_type, fields),
                "sortCreator": itemdata.derive_sort_creator(creators),
                "sortDate": itemdata.derive_sort_date(item_type, fields),
                "dateAdded": added.isoformat(sep=" "),
                "dateModified": modified.isoformat(sep=" "),
                "serverDateModified": modified.isoformat(sep=" "),
                "fields": [{"field": name, "value": value} for name, value in fields.items()],
                "creators": [
                    {
                        "position": creator.position,
                        "creatorType": creator.creator_type,
                        "firstName": creator.first_name,
                        "lastName": creator.last_name,
                        "name": creator.name,
                    }
                    for creator in creators
                ],
                "relations": relations,
            }
        )

        for name, tag_type in parsed["tags"]:
            self.tags.setdefault((name, tag_type), []).append(key)
        for collection_key in parsed["collections"]:
            self.membership.setdefault(str(collection_key), []).append(key)

        if fields.get("linkMode") in STORED_LINK_MODES and fields.get("md5"):
            self.files.append((key, fields["md5"]))


async def fetch_archive(
    api: ZoteroApi,
    *,
    destination: Path,
    target_user_id: int,
    report: Report | None = None,
) -> Summary:
    """Copy the key owner's personal library into an archive, and describe it.

    The library is the items, the collections and the saved searches; a request
    for one of those that will not answer stops the migration, because what
    would be left is not the library. Everything else -- the tags' versions, the
    settings, the full text, the deletion log, and each attachment's bytes --
    is read if it can be and noted in ``unavailable`` if it cannot. Somebody
    moving house does not want the van turned back for a missing lampshade,
    and losing twenty minutes of downloading to one endpoint having a bad day
    is what "as complete as possible" is against.

    It is not hypothetical. ``GET /users/<id>/tags?format=versions`` answers
    **500 on api.zotero.org**, for any limit and for any library, including
    Zotero's own documented example account -- while `/items`, `/collections`
    and `/searches` answer it perfectly. altero implements the same endpoint
    and answers it, which is exactly why reading from another altero did not
    show this up.

    Args:
        destination: Where to write the archive.
        target_user_id: The altero account it is destined for, which decides
            what the object URIs are rewritten to.
    """

    def say(stage: str, done: int = 0, total: int | None = None, detail: str = "") -> None:
        if report is not None:
            report(Progress(stage=stage, done=done, total=total, detail=detail))

    say("connecting")
    owner = await api.key_owner()
    source_id = int(owner["userID"])
    prefix = f"/users/{source_id}"

    access = (owner.get("access") or {}).get("user") or {}
    if not access.get("library"):
        raise InvalidInputError(
            "That key cannot read your library. Give it 'Allow library access' at zotero.org."
        )

    assembler = _Assembler(_rewriter(source_id, target_user_id))
    summary = assembler.summary
    summary.user_id = source_id
    summary.username = str(owner.get("username") or "")

    async def optional(part: str, request: Awaitable[Any]) -> Any:
        """Read something the copy can do without, or note that it would not.

        A refused *credential* still stops everything: that is not one endpoint
        having a bad day, it is the whole migration having no way in.
        """
        try:
            return await request
        except (ZoteroApiError, httpx.HTTPError) as thrown:
            logger.warning("could not read %s from %s: %s", part, api.base_url, thrown)
            if part not in summary.unavailable:
                summary.unavailable.append(part)
            return None

    # Read before the contents rather than after, so a library somebody is
    # still syncing into is recorded at a version no later than what was read.
    summary.library_version = await api.library_version(prefix)

    say("items")
    async for page in api.paged(f"{prefix}/items", includeTrashed=1):
        for envelope in page:
            assembler.add_item(envelope)
        say("items", done=len(assembler.items))
    summary.items = len(assembler.items)

    say("collections")
    collections: list[dict[str, Any]] = []
    async for page in api.paged(f"{prefix}/collections"):
        for envelope in page:
            data = envelope.get("data") or {}
            key = str(data.get("key") or envelope.get("key"))
            parent = data.get("parentCollection")
            collections.append(
                {
                    "key": key,
                    "version": int(envelope.get("version") or data.get("version") or 0),
                    "name": str(data.get("name") or ""),
                    "parent": str(parent) if parent else None,
                    "deleted": bool(data.get("deleted", False)),
                    "dateAdded": _now(),
                    "dateModified": _now(),
                    "serverDateModified": _now(),
                    "items": sorted(assembler.membership.get(key, [])),
                    "relations": [
                        {"predicate": predicate, "object": assembler.rewrite(str(obj))}
                        for predicate, objects in (data.get("relations") or {}).items()
                        for obj in (objects if isinstance(objects, list) else [objects])
                    ],
                }
            )
        say("collections", done=len(collections))
    summary.collections = len(collections)

    say("searches")
    searches: list[dict[str, Any]] = []
    async for page in api.paged(f"{prefix}/searches"):
        for envelope in page:
            data = envelope.get("data") or {}
            searches.append(
                {
                    "key": str(data.get("key") or envelope.get("key")),
                    "version": int(envelope.get("version") or data.get("version") or 0),
                    "name": str(data.get("name") or ""),
                    "deleted": bool(data.get("deleted", False)),
                    "dateAdded": _now(),
                    "dateModified": _now(),
                    "serverDateModified": _now(),
                    "conditions": [
                        {
                            "position": index,
                            "condition": str(condition.get("condition", "")),
                            "operator": str(condition.get("operator", "")),
                            "value": str(condition.get("value", "")),
                        }
                        for index, condition in enumerate(data.get("conditions") or [])
                    ],
                }
            )
        say("searches", done=len(searches))
    summary.searches = len(searches)

    # Versions by name, so a tag keeps the version clients remember it at. A
    # name that is both a manual and an automatic tag shares one version there,
    # which is upstream's own answer -- its `/tags?format=versions` is keyed by
    # name too.
    say("tags")
    tag_versions = (
        await optional("the tags' versions", api.json(f"{prefix}/tags", format="versions"))
    ) or {}
    tags = [
        {
            "key": generate_key(),
            "name": name,
            "type": tag_type,
            "version": int(tag_versions.get(name, summary.library_version)),
            "dateAdded": _now(),
            "dateModified": _now(),
            "serverDateModified": _now(),
            "items": sorted(keys),
        }
        for (name, tag_type), keys in sorted(assembler.tags.items())
    ]
    summary.tags = len(tags)

    say("settings")
    stored = await optional("the settings", api.json(f"{prefix}/settings")) or {}
    settings = [
        {
            "name": name,
            "value": json.dumps(body.get("value")),
            "version": int(body.get("version", 0)),
        }
        for name, body in (stored or {}).items()
        if isinstance(body, dict)
    ]
    summary.settings = len(settings)

    say("full text")
    indexed = await optional("the full-text index", api.json(f"{prefix}/fulltext", since=0)) or {}
    fulltext: list[dict[str, Any]] = []
    known = {entry["key"] for entry in assembler.items}
    for position, (item_key, version) in enumerate(sorted((indexed or {}).items()), start=1):
        if item_key not in known:
            continue
        body = await optional(
            "some attachments' text", api.json(f"{prefix}/items/{item_key}/fulltext")
        )
        if body is None:
            continue
        fulltext.append(
            {
                "item": item_key,
                "content": str(body.get("content", "")),
                "version": int(version),
                "indexedChars": body.get("indexedChars"),
                "totalChars": body.get("totalChars"),
                "indexedPages": body.get("indexedPages"),
                "totalPages": body.get("totalPages"),
            }
        )
        say("full text", done=position, total=len(indexed))
    summary.fulltext = len(fulltext)

    say("deleted")
    removed = await optional("the deletion log", api.json(f"{prefix}/deleted", since=0)) or {}
    plural = {
        "collections": "collection",
        "items": "item",
        "searches": "search",
        "settings": "setting",
        "tags": "tag",
    }
    deleted = [
        {
            "objectType": singular,
            "key": key,
            # No versions are served here, so everything is recorded at the
            # library's current version: a client asking what went since any
            # earlier point is then told about all of it.
            "version": summary.library_version,
            "deleted": _now(),
        }
        for group, singular in plural.items()
        for key in (removed or {}).get(group, [])
    ]
    summary.deleted = len(deleted)

    documents = {
        "items.json": assembler.items,
        "collections.json": collections,
        "searches.json": searches,
        "tags.json": tags,
        "settings.json": settings,
        "fulltext.json": fulltext,
        "deleted.json": deleted,
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, document in documents.items():
            bundle.writestr(name, json.dumps(document, indent=2))

        say("files", done=0, total=len(assembler.files))
        written: set[str] = set()
        for position, (item_key, digest) in enumerate(assembler.files, start=1):
            say("files", done=position, total=len(assembler.files), detail=item_key)
            if digest in written:
                continue
            body = await api.file(prefix, item_key)
            if body is None:
                summary.files_missing.append(item_key)
                continue
            if file_digest(body) != digest:
                # The item says one thing and the bytes another. Kept anyway --
                # it is the file that was there -- but the item is named so
                # somebody can look.
                logger.warning("digest of %s does not match what the item claims", item_key)
            bundle.writestr(f"{FILE_PREFIX}{digest}", body)
            written.add(digest)
        summary.files = len(written)

        bundle.writestr(
            MANIFEST,
            json.dumps(
                {
                    "format": FORMAT_VERSION,
                    "altero": __version__,
                    "library": {
                        "type": LibraryType.USER.value,
                        "id": target_user_id,
                        "version": summary.library_version,
                    },
                    "name": summary.username,
                    "source": {
                        "server": api.base_url,
                        "userID": source_id,
                        "username": summary.username,
                    },
                    "counts": {
                        "items": summary.items,
                        "collections": summary.collections,
                        "searches": summary.searches,
                        "tags": summary.tags,
                        "settings": summary.settings,
                        "fulltext": summary.fulltext,
                        "deleted": summary.deleted,
                        "files": summary.files,
                    },
                },
                indent=2,
            ),
        )

    say("done", done=summary.items, total=summary.items)
    return summary
