"""Creating, updating, filing, copying and deleting items.

Every path that writes an item passes through :func:`save_item`,
:func:`refile_items` or :func:`delete_items`, which is why the finer group
permissions are enforced in those three rather than in the eight routes that
call them. A ``permit`` of ``None`` means an unrestricted write -- a restore, a
migration, the command line -- and every route hands its caller's
:class:`~altero.services.auth.Access` instead.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.db import chunked
from altero.errors import ForbiddenError, InvalidInputError, NotFoundError
from altero.itemschema import get_schema
from altero.keys import coerce_key, is_valid_key
from altero.models import (
    Collection,
    CollectionItem,
    DeletedObjectType,
    FullText,
    Item,
    ItemCreator,
    ItemField,
    ItemRelation,
    ItemTag,
    Library,
    LibraryType,
    StorageDownload,
    StorageUpload,
    Tag,
    TagType,
)
from altero.services import itemdata
from altero.services.auth import Access
from altero.services.deletions import record_deletions
from altero.services.items import confined_to_collections, get_item, in_collections, tags_for
from altero.services.objectwrites import parse_relations, resolve_tags
from altero.services.writes import check_object_version

#: Keys of the item JSON that are not field values.
STRUCTURAL_KEYS = frozenset(
    {
        "key",
        "version",
        "itemType",
        "parentItem",
        "creators",
        "tags",
        "collections",
        "relations",
        "dateAdded",
        "dateModified",
        "deleted",
        "inPublications",
        # `note` is not in the schema's field list for any type, so it is
        # handled on its own below rather than as an ordinary field.
        "note",
    }
)

#: Properties holding a list of things rather than one value, and which a
#: partial write therefore clears by sending empty rather than by omitting.
LIST_PROPERTIES = ("creators", "tags", "collections", "relations")

#: Item types whose JSON carries a `note` property.
NOTE_BEARING_TYPES = frozenset({"note", "attachment"})

#: Fields an item type accepts that the published schema does not list.
#:
#: The schema gives `attachment` only title, accessDate and url, and `note` and
#: `annotation` nothing at all, yet all three carry more than that in practice.
#: The attachment set was read off live responses and off the server's own
#: `/items/new` templates; the annotation set comes from the client's data model,
#: since the published schema names none of it.
#:
#: Ordered rather than sets, because the order is the one the API emits these in
#: and the client depends on it: see :func:`altero.serializers.ordered_fields`.
#: What an attachment says about the file it holds, set when one is registered.
#: Upstream skips a write naming either empty and serves both as null until then,
#: on the link modes that store a file (:data:`STORED_FILE_LINK_MODES`).
FILE_STATE_FIELDS = ("md5", "mtime")

#: The link modes whose attachment has a file on the server.
STORED_FILE_LINK_MODES = frozenset({"imported_file", "imported_url", "embedded_image"})

UNLISTED_FIELDS: dict[str, tuple[str, ...]] = {
    "attachment": (
        "linkMode",
        "contentType",
        "charset",
        "filename",
        "md5",
        "mtime",
        "path",
        # Added at schema version 42; the client uploads it on its own when
        # a snapshot is opened.
        "lastRead",
    ),
    "annotation": (
        "annotationType",
        "annotationAuthorName",
        "annotationText",
        "annotationComment",
        "annotationColor",
        "annotationPageLabel",
        "annotationSortIndex",
        "annotationPosition",
    ),
}


def _parse_timestamp(value: Any, name: str) -> datetime | None:
    """Return a client-supplied timestamp, or ``None`` if it was not given.

    Clients round-trip their own ``dateAdded`` and ``dateModified``; dropping
    them would rewrite a library's history to the moment it was uploaded.
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise InvalidInputError(f"Invalid '{name}' value '{value}'") from None


def _validate_creators(item_type: str, creators: Any) -> list[dict[str, str]]:
    """Check the ``creators`` array and return it normalised."""
    if not isinstance(creators, list):
        raise InvalidInputError("'creators' must be an array")

    valid = get_schema().get_item_type(item_type).creator_type_names
    normalised: list[dict[str, str]] = []

    for creator in creators:
        if not isinstance(creator, dict):
            raise InvalidInputError("Invalid creator")

        creator_type = creator.get("creatorType")
        if creator_type not in valid:
            raise InvalidInputError(
                f"'{creator_type}' is not a valid creator type for type '{item_type}'"
            )

        if "name" in creator:
            normalised.append({"creatorType": creator_type, "name": str(creator["name"])})
        else:
            normalised.append(
                {
                    "creatorType": creator_type,
                    "firstName": str(creator.get("firstName", "")),
                    "lastName": str(creator.get("lastName", "")),
                }
            )
    return normalised


def _validate_tags(tags: Any) -> list[tuple[str, int]]:
    """Check the ``tags`` array and return ``(name, type)`` pairs."""
    if not isinstance(tags, list):
        raise InvalidInputError("'tags' must be an array")

    result: list[tuple[str, int]] = []
    for tag in tags:
        if not isinstance(tag, dict) or "tag" not in tag:
            raise InvalidInputError("Invalid tag")
        name = str(tag["tag"])
        if not name:
            raise InvalidInputError("Tag cannot be empty")
        tag_type = int(tag.get("type", TagType.MANUAL))
        if tag_type not in (TagType.MANUAL, TagType.AUTOMATIC):
            raise InvalidInputError(f"Invalid tag type '{tag_type}'")
        # A tag named twice is carried once, as upstream's `Zotero_Tag::addItem`
        # skips an item the tag already has. A name under two types is two tags.
        if (name, tag_type) not in result:
            result.append((name, tag_type))
    return result


def _validate_publications(
    payload: dict[str, Any],
    item_type: str,
    library_type: LibraryType,
    existing: Item | None,
) -> bool:
    """Return whether the item belongs to My Publications, refusing if it cannot.

    The checks and their order are upstream's: a falsy value is accepted
    without further question, and only a true one has to earn it.
    """
    if not payload.get("inPublications"):
        return False

    if library_type is not LibraryType.USER:
        raise InvalidInputError(
            f"{library_type.value.capitalize()} items cannot be added to My Publications"
        )

    is_child = bool(payload.get("parentItem")) or (existing is not None and existing.parent_id)
    if not is_child and item_type in NOTE_BEARING_TYPES:
        raise InvalidInputError(
            "Top-level notes and attachments cannot be added to My Publications"
        )

    if item_type == "attachment":
        link_mode = payload.get("linkMode")
        if link_mode is None and existing is not None:
            link_mode = existing.field_values().get("linkMode")
        if str(link_mode).lower() == "linked_file":
            raise InvalidInputError("Linked-file attachments cannot be added to My Publications")

    return True


def validate_item(
    payload: dict[str, Any],
    existing: Item | None = None,
    library_type: LibraryType = LibraryType.USER,
) -> dict[str, Any]:
    """Check an item's JSON against the schema and return its parts.

    Args:
        existing: The stored item, when the payload addresses one. An object
            that names an existing item and omits ``itemType`` is a partial
            update, and takes the type from that item.
        library_type: Which kind of library is being written to. Only a
            personal library has a My Publications.

    Raises:
        InvalidInputError: if the item type, a field or a creator type is not
            valid for this item.
    """
    item_type = payload.get("itemType")
    if not isinstance(item_type, str):
        if existing is None:
            raise InvalidInputError("'itemType' property not provided")
        item_type = existing.item_type

    schema = get_schema()
    type_ = schema.get_item_type(item_type)

    if (key := payload.get("key")) is not None and key != "" and not is_valid_key(str(key)):
        raise InvalidInputError(f"'{key}' is not a valid item key")

    unlisted = UNLISTED_FIELDS.get(item_type, ())

    fields: dict[str, str] = {}
    for name, value in payload.items():
        if name in STRUCTURAL_KEYS:
            continue
        if name in unlisted:
            # `md5` and `mtime` are null in an empty template, and null means
            # absent rather than the string "None". Upstream skips them empty as
            # well, so they are never stored as "" and are served as null.
            if value is not None and not (name in FILE_STATE_FIELDS and value == ""):
                fields[name] = str(value)
            continue
        if name not in schema.all_field_names:
            raise InvalidInputError(f"Invalid field '{name}'")
        if name not in type_.field_names:
            raise InvalidInputError(f"'{name}' is not a valid field for type '{item_type}'")
        fields[name] = "" if value is None else str(value)

    # Notes carry their content outside the schema's field list.
    if item_type in NOTE_BEARING_TYPES:
        # Items::updateFromJSON calls setNote only for a supplied property.
        # An omitted note in a partial upload must not erase its stored text.
        if "note" in payload or existing is None:
            fields["note"] = str(payload.get("note", ""))
    elif "note" in payload:
        raise InvalidInputError(f"'note' is not a valid field for type '{item_type}'")

    collections = payload.get("collections", [])
    if not isinstance(collections, list):
        raise InvalidInputError("'collections' must be an array")

    # Shared with collections, so both accept the empty array upstream allows
    # and both expand a predicate naming several objects.
    relations = parse_relations(payload)

    parsed = {
        "item_type": item_type,
        "key": payload.get("key") or None,
        "version": payload.get("version"),
        "parent_item": payload.get("parentItem") or None,
        "fields": fields,
        "creators": _validate_creators(item_type, payload.get("creators", [])),
        "tags": _validate_tags(payload.get("tags", [])),
        "collections": [str(key) for key in collections],
        "relations": relations,
        "date_added": _parse_timestamp(payload.get("dateAdded"), "dateAdded"),
        "date_modified": _parse_timestamp(payload.get("dateModified"), "dateModified"),
        # Which of the list-valued properties the object actually carried.
        # `updateFromJSON` walks the properties that are there --
        # `foreach ($json as $key=>$val)` -- and hands each to its setter, so an
        # empty array reaches `setCollections([])` and empties the list. Only an
        # absent property is left alone. Reading empty and absent as one thing
        # left no way to say "none", and `_apply` is where the difference is
        # spent.
        "mentioned": {name for name in LIST_PROPERTIES if name in payload},
    }

    # The two flags are carried only when the object mentions them, because
    # that is the difference upstream makes between "set it to false" and "I am
    # not talking about it": `if (isset($json->deleted) || !$partialUpdate)`,
    # and the same line again for `inPublications`. A patch that restated
    # neither would otherwise take an item out of the trash and out of My
    # Publications while changing its title. `_apply` clears both when the
    # write replaces, which is where the second half of that condition lives.
    if "deleted" in payload:
        parsed["deleted"] = bool(payload["deleted"])
    if "inPublications" in payload:
        parsed["in_publications"] = _validate_publications(
            payload, item_type, library_type, existing
        )

    return parsed


@dataclass(frozen=True, slots=True)
class _Links:
    """An item's tag and collection links as stored, by what they name."""

    tags: dict[tuple[str, int], int]
    collections: dict[str, int]


async def _links(session: AsyncSession, item: Item) -> _Links:
    """Read the tags and collections ``item`` carries, one statement each."""
    tags = await session.execute(
        select(Tag.name, Tag.type, Tag.id)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(ItemTag.item_id == item.id)
    )
    collections = await session.execute(
        select(Collection.key, Collection.id)
        .join(CollectionItem, CollectionItem.collection_id == Collection.id)
        .where(CollectionItem.item_id == item.id)
    )
    return _Links(
        tags={(name, type_): tag_id for name, type_, tag_id in tags.tuples()},
        collections=dict(collections.tuples().all()),
    )


class _State(NamedTuple):
    """Everything about an item that a client can change.

    Deliberately excludes the version and ``serverDateModified``, which the
    server sets: comparing those would make every object look different. The
    sort keys are excluded too, being derived from the fields.
    """

    item_type: str
    deleted: bool
    in_publications: bool
    date_added: datetime | None
    date_modified: datetime | None
    parent_id: int | None
    fields: tuple[tuple[str, str], ...]
    creators: tuple[tuple[Any, ...], ...]
    relations: tuple[tuple[str, str], ...]
    tags: tuple[tuple[str, int], ...]
    collections: tuple[str, ...]


def _state(item: Item, links: _Links) -> _State:
    """``item`` as stored, with the links it carries."""
    return _State(
        item_type=item.item_type,
        deleted=item.deleted,
        in_publications=item.in_publications,
        date_added=item.date_added,
        date_modified=item.date_modified,
        parent_id=item.parent_id,
        fields=tuple(sorted((entry.field, entry.value) for entry in item.fields)),
        creators=tuple(
            (
                creator.position,
                creator.creator_type,
                creator.first_name,
                creator.last_name,
                creator.name,
            )
            for creator in sorted(item.creators, key=lambda c: c.position)
        ),
        relations=tuple(
            sorted((relation.predicate, relation.object) for relation in item.relations)
        ),
        tags=tuple(sorted(links.tags)),
        collections=tuple(sorted(links.collections)),
    )


def _predict(
    before: _State, parsed: dict[str, Any], *, replace: bool, parent_id: int | None, now: datetime
) -> _State:
    """The state :func:`_apply` would leave ``before`` in, worked out without writing.

    Each line is the rule ``_apply`` follows for the same property, and
    ``tests/test_unchanged.py`` holds the two together by putting every payload
    shape both ways.
    """
    mentioned = parsed["mentioned"]
    fields = dict(parsed["fields"]) if replace else dict(before.fields) | parsed["fields"]
    return _State(
        item_type=parsed["item_type"],
        deleted=(
            parsed.get("deleted", False) if replace or "deleted" in parsed else before.deleted
        ),
        in_publications=(
            parsed.get("in_publications", False)
            if replace or "in_publications" in parsed
            else before.in_publications
        ),
        date_added=parsed["date_added"] or before.date_added or now,
        date_modified=parsed["date_modified"] or now,
        parent_id=parent_id if parent_id is not None or replace else before.parent_id,
        fields=tuple(sorted(fields.items())),
        creators=(
            tuple(
                (
                    index,
                    creator["creatorType"],
                    creator.get("firstName"),
                    creator.get("lastName"),
                    creator.get("name"),
                )
                for index, creator in enumerate(parsed["creators"])
            )
            if replace or "creators" in mentioned
            else before.creators
        ),
        relations=(
            tuple(sorted(parsed["relations"]))
            if replace or "relations" in mentioned
            else before.relations
        ),
        tags=tuple(sorted(parsed["tags"])) if replace or "tags" in mentioned else before.tags,
        collections=(
            tuple(sorted(set(parsed["collections"])))
            if replace or "collections" in mentioned
            else before.collections
        ),
    )


async def _parent_id(
    session: AsyncSession, library: Library, parsed: dict[str, Any], permit: Access | None
) -> int | None:
    """The id of the parent ``parsed`` names, or ``None`` if it names none."""
    if parsed["parent_item"] is None:
        return None
    parent = await get_item(
        session, library, str(parsed["parent_item"]), permit=permit, related=False
    )
    return parent.id


async def _apply(
    session: AsyncSession,
    library: Library,
    item: Item,
    parsed: dict[str, Any],
    version: int,
    *,
    replace: bool,
    permit: Access | None = None,
    parent_id: int | None = None,
    links: _Links | None = None,
) -> None:
    """Write ``parsed`` onto ``item``, adding it to the session if it is new.

    Everything stored on the item's own row is settled before the first query
    that could flush it, so a new item is one INSERT and a changed one one
    UPDATE, rather than an INSERT or UPDATE followed by another for the parent
    and another for the sort keys.

    Args:
        replace: Whether omitted properties are cleared. ``PUT`` replaces,
            ``PATCH`` leaves anything it does not mention alone.
        parent_id: The parent ``parsed`` names, already looked up -- the lookup
            flushes, and anything assigned before it would be written by it and
            then written again.
        links: The tags and collections the item carries, if already read. A
            new item carries none.
    """
    relinking = replace or bool({"tags", "collections"} & parsed["mentioned"])
    if links is None and relinking:
        links = _Links({}, {}) if item.id is None else await _links(session, item)
    session.add(item)

    item.item_type = parsed["item_type"]
    item.version = version
    # A partial update leaves alone what it did not mention -- `validate_item`
    # carries the flag only when the object named it -- and a replacing write
    # means what it omits.
    if replace or "deleted" in parsed:
        item.deleted = parsed.get("deleted", False)
    if replace or "in_publications" in parsed:
        item.in_publications = parsed.get("in_publications", False)

    # Client timestamps round-trip; the server's own is always now, which is what
    # makes sorting by `serverDateModified` trustworthy.
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    if parsed["date_added"] is not None:
        item.date_added = parsed["date_added"]
    elif item.date_added is None:
        item.date_added = now
    item.date_modified = parsed["date_modified"] or now
    item.server_date_modified = now

    if replace:
        item.fields = [
            ItemField(field=name, value=value) for name, value in parsed["fields"].items()
        ]
    else:
        existing = {field.field: field for field in item.fields}
        for name, value in parsed["fields"].items():
            if name in existing:
                existing[name].value = value
            else:
                item.fields.append(ItemField(field=name, value=value))

    if replace or "creators" in parsed["mentioned"]:
        item.creators = [
            ItemCreator(
                position=index,
                creator_type=creator["creatorType"],
                first_name=creator.get("firstName"),
                last_name=creator.get("lastName"),
                name=creator.get("name"),
            )
            for index, creator in enumerate(parsed["creators"])
        ]

    if replace or "relations" in parsed["mentioned"]:
        item.relations = [
            ItemRelation(predicate=predicate, object=obj) for predicate, obj in parsed["relations"]
        ]

    if parent_id is not None or replace:
        item.parent_id = parent_id

    # Sort keys are recomputed from whatever the item now holds, so a PATCH that
    # changes only the title still reorders correctly.
    values = item.field_values()
    item.sort_title = itemdata.derive_sort_title(item.item_type, values)
    item.sort_creator = itemdata.derive_sort_creator(item.creators)
    item.sort_date = itemdata.derive_sort_date(item.item_type, values)

    # An update that rewrites no links can wait for whatever flushes next, so a
    # selection's worth of them goes out together. A new item always has its
    # links written, if only as none.
    if links is None:
        return

    await session.flush()

    if replace or "tags" in parsed["mentioned"]:
        await _retag(session, library, item, parsed["tags"], version, links.tags)

    if replace or "collections" in parsed["mentioned"]:
        await _refile(session, library, item, parsed["collections"], links.collections)


async def _retag(
    session: AsyncSession,
    library: Library,
    item: Item,
    wanted: list[tuple[str, int]],
    version: int,
    current: dict[tuple[str, int], int],
) -> None:
    """Give ``item`` exactly the tags ``wanted``, touching only the links that differ.

    Every tag named takes ``version``, whether its link is new or not.
    """
    named = set(wanted)
    gone = [tag_id for pair, tag_id in current.items() if pair not in named]
    if gone:
        await session.execute(
            delete(ItemTag).where(ItemTag.item_id == item.id, ItemTag.tag_id.in_(gone))
        )

    tags = await resolve_tags(session, library, wanted)
    for pair in wanted:
        tags[pair].version = version
        if pair not in current:
            session.add(ItemTag(item_id=item.id, tag_id=tags[pair].id))


async def _refile(
    session: AsyncSession, library: Library, item: Item, keys: list[str], stored: dict[str, int]
) -> None:
    """Put ``item`` in exactly the collections ``keys``, touching only the links that differ."""
    wanted = list(dict.fromkeys(keys))
    ids: dict[str, int] = {}
    if wanted:
        rows = await session.execute(
            select(Collection.key, Collection.id).where(
                Collection.library_id == library.id, Collection.key.in_(wanted)
            )
        )
        ids = dict(rows.tuples().all())
    for key in wanted:
        if key not in ids:
            raise InvalidInputError(f"Collection {key} not found")

    current = set(stored.values())
    filed = [ids[key] for key in wanted]
    gone = current - set(filed)
    if gone:
        await session.execute(
            delete(CollectionItem).where(
                CollectionItem.item_id == item.id, CollectionItem.collection_id.in_(gone)
            )
        )
    for collection_id in filed:
        if collection_id not in current:
            session.add(CollectionItem(collection_id=collection_id, item_id=item.id))


async def save_item(
    session: AsyncSession,
    library: Library,
    payload: dict[str, Any],
    version: int,
    *,
    key: str | None = None,
    replace: bool = True,
    require_version: bool = False,
    detect_unchanged: bool = False,
    actor_id: int | None = None,
    permit: Access | None = None,
    stored: Item | None = None,
) -> Item | None:
    """Create or update one item and return it.

    Args:
        version: Library version to stamp the item with.
        key: Key of the item being addressed, for key-based writes.
        replace: Whether omitted properties are cleared.
        require_version: Whether the payload must state the version it replaces.
        detect_unchanged: Return ``None``, writing nothing, when the payload
            describes what is already stored.
        actor_id: Who is writing. Recorded in a group library so the item can
            say who added it and who last changed it.
        permit: What the caller may write. ``None`` for a path with no
            credential to hold to -- a restore, an import, the command line.
        stored: The item ``key`` names, when the caller already holds it.
    """
    # The item has to be resolved before validation, because an object naming an
    # existing item may omit properties that a new one must carry.
    target_key = key or (payload.get("key") if is_valid_key(str(payload.get("key", ""))) else None)

    item = stored
    if item is None and target_key:
        item = await session.scalar(
            select(Item).where(Item.library_id == library.id, Item.key == str(target_key))
        )

    if item is None and target_key:
        check_object_version(0, payload.get("version"), required=False)
    parsed = validate_item(payload, item, library.type)

    # An object that addresses an existing item without restating its type is a
    # diff against what the server already holds, so it must not clear the rest.
    if item is not None and "itemType" not in payload:
        replace = False
    # A new item has nothing to preserve, so writing it as a diff and writing it
    # as a replacement describe the same result. It is written as a replacement
    # because that assigns the field, creator and relation collections rather
    # than reading them, and reading an unloaded collection off a row that has
    # just been flushed is a lazy load -- which under async SQLAlchemy is a
    # `MissingGreenlet` rather than a query. `save_collection` and `save_search`
    # reach the same place by treating an object as partial only when it names
    # one that exists.
    if item is None:
        replace = True

    links = None
    creating = item is None
    if item is None:
        # Added by `_apply`, once the parent is known.
        item = Item(
            library_id=library.id,
            key=coerce_key(str(target_key) if target_key else None),
            version=version,
        )
    else:
        if permit is not None:
            if permit.collections is not None and not await in_collections(
                session, item, permit.collections
            ):
                # An item outside a resource-scoped grant is not found, exactly
                # as it is on the way in -- so a write cannot be used to ask
                # whether a key exists after a read was refused for saying so.
                raise NotFoundError("Item does not exist")
            # Asked of the item as stored, before anything is applied to it.
            # Trashing is asked separately, because sending `deleted` on
            # something already in the trash is not a removal and re-sending an
            # item unchanged should not be refused as one.
            permit.require_change(item.created_by_user_id)
            if parsed.get("deleted") and not item.deleted:
                permit.require_remove(item.created_by_user_id)
        check_object_version(item.version, parsed["version"], required=require_version)

    # Looked up before anything is assigned: see `_apply`.
    parent_id = await _parent_id(session, library, parsed, permit)

    if detect_unchanged and not creating:
        # Decided by what writing would produce rather than by writing it and
        # looking: the comparison upstream makes, at the cost of reading the
        # links, which writing would have read anyway.
        links = await _links(session, item)
        before = _state(item, links)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if before == _predict(before, parsed, replace=replace, parent_id=parent_id, now=now):
            return None

    # Who wrote it is stamped with everything else, so it is not an UPDATE of
    # its own, and only once the write is known to change something: re-sending
    # an item exactly as stored does not rewrite who last touched it. Upstream
    # reaches the same place from the other direction: nothing is written, so
    # its `groupItems` update never runs.
    if library.type is LibraryType.GROUP and actor_id is not None:
        if creating:
            # Upstream inserts both columns on create, and its serialiser then
            # collapses them because they are equal.
            item.created_by_user_id = actor_id
        item.last_modified_by_user_id = actor_id

    await _apply(
        session,
        library,
        item,
        parsed,
        version,
        replace=replace,
        permit=permit,
        parent_id=parent_id,
        links=links,
    )

    if permit is not None and permit.collections is not None:
        # Asked again of the item as written. A confined credential may move an
        # item between the collections it was given and may not walk one out of
        # them -- nor create one outside them, which is the same question asked
        # of a row that did not exist a moment ago. `session.flush` has already
        # run inside `_apply`, so the collection rows this reads are the new
        # ones and the answer is about what the write actually produced.
        await session.flush()
        if not await in_collections(session, item, permit.collections):
            raise ForbiddenError(
                "This application was given access to particular collections, "
                "and this item is not in any of them"
            )

    return item


async def refile_items(
    session: AsyncSession,
    library: Library,
    items: Sequence[Item],
    version: int,
    *,
    add: Sequence[str] = (),
    remove: Sequence[str] = (),
    actor_id: int | None = None,
    permit: Access | None = None,
) -> None:
    """File ``items`` into the collections ``add`` and out of those in ``remove``.

    Filing is an add-and-remove errand computed from what is stored, so it
    states no version and restates none of the item: :func:`save_item` would
    take the caller's whole idea of the item and write that, and the browser's
    idea of it may be minutes stale. Where each item is filed now is read here
    for the same reason: a collection added from the desktop since the page was
    drawn must not disappear because the browser did not know about it.

    Everything else about the items is left alone, ``deleted`` included: filing
    something is not untrashing it.

    Filing is a change to the *item*, not to the collections, which is why a
    member restricted to their own items may file one of theirs into a
    collection somebody else made -- and may not file somebody else's item
    anywhere.

    A statement per kind of row for the whole selection, not per item.
    """
    ids = [item.id for item in items]
    confined = permit.collections if permit is not None else None
    if permit is not None:
        inside: set[int] = set()
        if confined is not None:
            for chunk in chunked(ids):
                inside.update(
                    await session.scalars(
                        select(Item.id).where(Item.id.in_(chunk), confined_to_collections(confined))
                    )
                )
        for item in items:
            if confined is not None and item.id not in inside:
                raise NotFoundError("Item does not exist")
            permit.require_change(item.created_by_user_id)

    filed: dict[int, dict[str, int]] = {item_id: {} for item_id in ids}
    for chunk in chunked(ids):
        rows = await session.execute(
            select(CollectionItem.item_id, Collection.key, Collection.id)
            .join(Collection, Collection.id == CollectionItem.collection_id)
            .where(CollectionItem.item_id.in_(chunk))
        )
        for item_id, key, collection_id in rows.tuples():
            filed[item_id][key] = collection_id

    adding = list(dict.fromkeys(add))
    found: dict[str, int] = {}
    if adding:
        rows = await session.execute(
            select(Collection.key, Collection.id).where(
                Collection.library_id == library.id, Collection.key.in_(adding)
            )
        )
        found = dict(rows.tuples().all())

    for item in items:
        keep = {key: cid for key, cid in filed[item.id].items() if key not in remove}
        for key in adding:
            if key in keep:
                continue
            if key not in found:
                raise NotFoundError(f"Collection {key} not found")
            keep[key] = found[key]
        if confined is not None:
            # Filing is a write to the item, and the item has to stay inside
            # the grant afterwards. A collection the caller cannot see is not
            # found rather than refused, as it is everywhere else.
            for key, collection_id in keep.items():
                if collection_id not in confined:
                    raise NotFoundError(f"Collection {key} not found")
            if not keep:
                # Filing something nowhere takes it out of every collection,
                # and out of the grant with them. Refused rather than allowed
                # and then lost.
                raise ForbiddenError(
                    "This application was given access to particular collections, "
                    "and this would take the item out of all of them"
                )
        for key, collection_id in keep.items():
            if key not in filed[item.id]:
                session.add(CollectionItem(collection_id=collection_id, item_id=item.id))

    # Named on both sides, a collection ends up filed, as it does above.
    removing = [key for key in dict.fromkeys(remove) if key not in found]
    if removing:
        removed = select(Collection.id).where(
            Collection.library_id == library.id, Collection.key.in_(removing)
        )
        for chunk in chunked(ids):
            await session.execute(
                delete(CollectionItem).where(
                    CollectionItem.item_id.in_(chunk), CollectionItem.collection_id.in_(removed)
                )
            )

    # The items changed, so they take the new version and a fresh timestamp: a
    # client that has them must hear about this, and where an item is filed is
    # part of what it syncs.
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    for item in items:
        item.version = version
        item.date_modified = now
        item.server_date_modified = now
        if library.type is LibraryType.GROUP and actor_id is not None:
            item.last_modified_by_user_id = actor_id

    await session.flush()


async def _copyable(session: AsyncSession, item: Item) -> dict[str, Any]:
    """Return ``item`` as a payload that would create it again elsewhere.

    What is left out is what belongs to the library it came from rather than to
    the item: its key and version, which the copy gets its own of; its
    collections, because those collections are in the other library; its
    relations, which name objects by URI and would point at the original
    library's items; and ``inPublications``, which is a decision about *this*
    library's public profile rather than a property of the work.
    """
    payload: dict[str, Any] = {"itemType": item.item_type}
    payload.update(item.field_values())

    if item.creators:
        payload["creators"] = [
            {"creatorType": creator.creator_type, "name": creator.name}
            if creator.name is not None
            else {
                "creatorType": creator.creator_type,
                "firstName": creator.first_name or "",
                "lastName": creator.last_name or "",
            }
            for creator in item.creators
        ]

    tags = (await tags_for(session, [item])).get(item.id, [])
    payload["tags"] = [
        {"tag": name} if type_ == TagType.MANUAL else {"tag": name, "type": type_}
        for name, type_ in tags
    ]
    return payload


async def copy_item(
    session: AsyncSession,
    target: Library,
    item: Item,
    version: int,
    *,
    collection_key: str | None = None,
    actor_id: int | None = None,
) -> Item:
    """Copy ``item`` and its children into ``target``, and return the copy.

    A copy and not a move: the original is untouched, which is what dragging
    between libraries does in the desktop client. The copy is a new item in the
    library it lands in -- its own key, its own version, its own ``dateAdded``
    -- because that is what it is. Nothing links it back to the original;
    Zotero's own relation for that is written by the client that made the copy,
    and a server that invented one would be claiming the two are the same work
    on the strength of a drag.

    An attached file needs no copying at all: files are stored under their
    digest, so the copy names the same bytes the original does. Full-text
    content is not carried over -- it is indexed from the file, and the client
    that holds the file will send it again.
    """
    payload = await _copyable(session, item)
    if collection_key:
        payload["collections"] = [collection_key]

    copy = await save_item(session, target, payload, version, actor_id=actor_id)
    assert copy is not None  # A new item is never "unchanged".

    # Children go with it. A note or an attachment cannot stand on its own, and
    # a copy of a book without the note somebody wrote on it is not the copy
    # they asked for.
    children = await session.scalars(
        select(Item).where(Item.parent_id == item.id).order_by(Item.id)
    )
    for child in list(children):
        child_payload = await _copyable(session, child)
        child_payload["parentItem"] = copy.key
        await save_item(session, target, child_payload, version, actor_id=actor_id)

    return copy


#: How deep the walk below the named items goes before it gives up. Zotero
#: nests three levels at most -- an annotation under an attachment under an
#: item -- so anything deeper is a loop in the parent column, not a library.
_DEEPEST = 16


async def _remove(
    session: AsyncSession, library: Library, named: dict[int, str], version: int
) -> None:
    """Remove the items ``named`` by id, everything below them, and the rows that point at them.

    A statement per table per chunk rather than several per item: the trash a
    reader empties can hold thousands.
    """
    # A note or attachment cannot outlive its parent: it has nothing left to
    # attach to, and the row it points at would be gone. Each item is deleted
    # at the deepest level it is found at, so that whatever is below it goes
    # first -- including an item that was named and is also below another.
    depth = dict.fromkeys(named, 0)
    keys = dict(named)
    frontier = list(named)
    for level in range(1, _DEEPEST + 1):
        below: list[int] = []
        for chunk in chunked(frontier):
            rows = await session.execute(select(Item.id, Item.key).where(Item.parent_id.in_(chunk)))
            for item_id, key in rows.tuples():
                depth[item_id] = level
                keys[item_id] = key
                below.append(item_id)
        if not below:
            break
        frontier = below
    else:
        raise InvalidInputError("Items nest deeper than any library can")

    everything = list(depth)
    tag_ids: set[int] = set()
    for chunk in chunked(everything):
        tag_ids.update(
            await session.scalars(select(ItemTag.tag_id).where(ItemTag.item_id.in_(chunk)))
        )
        # An attachment's indexed text, any upload it had authorized and any
        # download it had permitted name the item by id as well, so leaving one
        # behind fails the foreign key on the way out -- which is what deleting
        # a PDF the client had indexed used to do. The stored bytes stay: files
        # are shared by digest, and another item may be the same file.
        for model in (
            ItemTag,
            CollectionItem,
            FullText,
            StorageUpload,
            StorageDownload,
            ItemField,
            ItemCreator,
            ItemRelation,
        ):
            await session.execute(delete(model).where(model.item_id.in_(chunk)))

    for level in sorted(set(depth.values()), reverse=True):
        at_level = [item_id for item_id, found in depth.items() if found == level]
        for chunk in chunked(at_level):
            await session.execute(delete(Item).where(Item.id.in_(chunk)))

    await _drop_unused_tags(session, sorted(tag_ids))
    await record_deletions(
        session, library, DeletedObjectType.ITEM, [keys[item_id] for item_id in everything], version
    )


async def _drop_unused_tags(session: AsyncSession, tag_ids: list[int]) -> None:
    """Remove tags that no item carries any more.

    A tag exists only through its items, so one left with none is invisible over
    the API; without this the row would linger.
    """
    for chunk in chunked(tag_ids):
        await session.execute(
            delete(Tag).where(
                Tag.id.in_(chunk),
                ~select(ItemTag.item_id).where(ItemTag.tag_id == Tag.id).exists(),
            )
        )


async def delete_items(
    session: AsyncSession,
    library: Library,
    keys: list[str],
    version: int,
    *,
    permit: Access | None = None,
) -> None:
    """Remove items outright and record the deletions for ``/deleted``.

    Every named item is asked about before any of them goes, so a batch a
    restricted member is only partly entitled to takes none of it: the
    alternative is a request that half succeeds and leaves nobody able to say
    which half.
    """
    named = list(dict.fromkeys(keys))
    found: dict[str, tuple[int, int | None]] = {}
    for chunk in chunked(named):
        rows = await session.execute(
            select(Item.key, Item.id, Item.created_by_user_id).where(
                Item.library_id == library.id, Item.key.in_(chunk)
            )
        )
        found.update((key, (item_id, author)) for key, item_id, author in rows.tuples())

    if permit is not None:
        inside: set[str] | None = None
        if permit.collections is not None:
            inside = set()
            for chunk in chunked(list(found)):
                inside.update(
                    await session.scalars(
                        select(Item.key).where(
                            Item.library_id == library.id,
                            Item.key.in_(chunk),
                            confined_to_collections(permit.collections),
                        )
                    )
                )
        for key in named:
            # Deleting something already gone is not an error.
            if key not in found:
                continue
            if inside is not None and key not in inside:
                # Not found, not forbidden: a refusal here would say the key
                # names something, which is what the grant was drawn to hide.
                raise NotFoundError("Item does not exist")
            permit.require_remove(found[key][1])

    if found:
        await _remove(
            session, library, {item_id: key for key, (item_id, _author) in found.items()}, version
        )
