"""Rendering of domain objects into the API's JSON shapes.

Like the service layer, this module is free of web-framework imports: callers
supply the base URL and receive plain dictionaries.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote_plus

from altero.itemschema import get_schema
from altero.models import (
    ApiKey,
    Collection,
    Group,
    Item,
    Library,
    LibraryType,
    SavedSearch,
    User,
)
from altero.services.itemdata import creator_summary, parsed_date
from altero.services.itemwrites import UNLISTED_FIELDS

#: Path segment used in URLs for each library type.
_PREFIX = {LibraryType.USER: "users", LibraryType.GROUP: "groups"}


def library_prefix(library: Library) -> str:
    """Return the ``/users/<id>`` or ``/groups/<id>`` prefix for ``library``."""
    return f"/{_PREFIX[library.type]}/{library.owner_id}"


def json_link(href: str) -> dict[str, str]:
    return {"href": href, "type": "application/json"}


def library_block(library: Library, base_url: str) -> dict[str, Any]:
    """Return the ``library`` block embedded in every object response.

    Upstream puts a single ``alternate`` link here, pointing at its web
    interface. altero has none, so ``links`` stays empty rather than naming a
    page that does not exist.
    """
    return {
        "type": library.type.value,
        "id": library.owner_id,
        "name": library.name,
        "links": {},
    }


def group(
    library: Library, group: Group, base_url: str, *, library_editing: str | None = None
) -> dict[str, Any]:
    """Render a group library.

    ``meta`` is not emitted yet: its ``created``, ``lastModified`` and
    ``numItems`` values need object timestamps that do not exist so far.

    Args:
        library_editing: What to report as ``libraryEditing``, when the caller
            has worked out that this requester sees something narrower than the
            stored policy -- see :func:`altero.services.groups.editing_for`.
            ``None`` reports what is stored.
    """
    return {
        "id": library.owner_id,
        "version": library.version,
        "links": {"self": json_link(f"{base_url}/groups/{library.owner_id}")},
        "data": {
            "id": library.owner_id,
            "version": library.version,
            "name": group.name,
            "owner": group.owner_id,
            "type": group.type,
            "description": group.description,
            "url": group.url,
            "libraryEditing": library_editing or group.library_editing,
            "libraryReading": group.library_reading,
            "fileEditing": group.file_editing,
        },
    }


def api_key(key: ApiKey, user: User, groups: dict[int, dict[str, bool]]) -> dict[str, Any]:
    """Render an API key and the access it grants.

    Args:
        groups: Per-group overrides, keyed by group ID.
    """
    access: dict[str, Any] = {
        "user": {
            "library": key.library_read,
            "files": key.files_read,
            "notes": key.notes_read,
            "write": key.library_write,
        }
    }

    group_access: dict[str, dict[str, bool]] = {}
    if key.all_groups_read or key.all_groups_write:
        group_access["all"] = {"library": key.all_groups_read, "write": key.all_groups_write}
    for group_id, permissions in groups.items():
        group_access[str(group_id)] = permissions
    if group_access:
        access["groups"] = group_access

    return {
        "key": key.key,
        "userID": user.id,
        "username": user.username,
        "displayName": user.display_name,
        # The desktop client reads this -- preferences_account.jsx calls
        # displayFields(keyInfo.username, { emails: keyInfo.emails }) -- even
        # though the published documentation never mentions it. A list,
        # because upstream accounts may hold several; altero holds one, and
        # only offers it once it has been confirmed.
        "emails": [user.email] if user.email and user.email_verified else [],
        "access": access,
    }


def timestamp(value: datetime) -> str:
    """Render a stored timestamp as the UTC form the API uses.

    Public because the Atom entries need the same rendering for the timestamps
    the JSON envelope of a collection or a saved search does not carry.
    """
    return value.replace(microsecond=0).isoformat() + "Z"


def _object_links(
    library: Library, base_url: str, kind: str, key: str, parent_key: str | None = None
) -> dict[str, Any]:
    prefix = f"{base_url}{library_prefix(library)}/{kind}"
    links: dict[str, Any] = {"self": json_link(f"{prefix}/{key}")}
    if parent_key:
        links["up"] = json_link(f"{prefix}/{parent_key}")
    return links


class Relation(Protocol):
    """A stored predicate-object pair, as items and collections both keep."""

    predicate: str
    object: str


def render_relations(relations: Sequence[Relation]) -> dict[str, str | list[str]]:
    """Render stored predicate-object pairs as the API's ``relations`` map.

    One object for a predicate is a string and several are an array, which is
    what ``Zotero_DataObject::getRelations`` builds. Keying a dict on the
    predicate alone would keep only the last -- and an item related to three
    others would come back related to one.
    """
    grouped: dict[str, list[str]] = {}
    for relation in relations:
        grouped.setdefault(relation.predicate, []).append(relation.object)
    return {
        predicate: objects[0] if len(objects) == 1 else objects
        for predicate, objects in grouped.items()
    }


def user_block(user: User) -> dict[str, Any]:
    """Render an account as the API names one.

    ``name`` follows ``Zotero_Users::getName``: the real name, or the username
    when there is none.

    Upstream also carries a ``links.alternate`` pointing at the person's
    profile on zotero.org. That is omitted here for the reason every other
    ``alternate`` link is -- see ``docs/compatibility.md``.
    """
    return {
        "id": user.id,
        "username": user.username,
        "name": user.display_name or user.username,
    }


def _authorship(obj: Item, library: Library, authors: Mapping[int, User]) -> dict[str, Any]:
    """Render who added the item and who last changed it.

    Group libraries only, and ``lastModifiedByUser`` is dropped when it is the
    same person as ``createdByUser``. Both rules are upstream's, in
    ``Zotero_Item::toResponseJSON``: a personal library has one author, and
    somebody adding an item and then fixing its title should read as one name
    rather than the same name twice.
    """
    if library.type is not LibraryType.GROUP:
        return {}

    rendered: dict[str, Any] = {}
    created_by = authors.get(obj.created_by_user_id) if obj.created_by_user_id else None
    if created_by is not None:
        rendered["createdByUser"] = user_block(created_by)

    if obj.last_modified_by_user_id and obj.last_modified_by_user_id != obj.created_by_user_id:
        modified_by = authors.get(obj.last_modified_by_user_id)
        if modified_by is not None:
            rendered["lastModifiedByUser"] = user_block(modified_by)

    return rendered


def ordered_fields(item_type: str, fields: Mapping[str, str]) -> dict[str, str]:
    """Return an item's fields in the order the API emits them.

    The order is not cosmetic. ``Zotero.Item.fromJSON``
    walks the object with ``for (let field in json)`` and, on reaching
    ``filename``, sets the attachment path -- which throws "Link mode must be
    set before setting attachment path" unless ``linkMode`` came first. An
    attachment that arrives the other way round is never saved: it goes into the
    client's ``syncQueue`` and is retried, and fails, on every sync.

    Field values are rows with no order of their own, so their stored order is
    whatever the database returns: insertion order under SQLite, unspecified
    under PostgreSQL. This puts them back into the schema's order, which is the
    one upstream emits and the one the client is written against.
    """
    order = list(UNLISTED_FIELDS.get(item_type, ())[:1])  # `linkMode`, for an attachment.
    order += [field.name for field in get_schema().get_item_type(item_type).fields]
    order += UNLISTED_FIELDS.get(item_type, ())[1:]
    # A note's content is not in the schema's field list for any type, and comes
    # last on the types that carry it.
    order.append("note")

    ordered = {name: fields[name] for name in order if name in fields}
    # Anything unrecognised keeps its stored position rather than being dropped.
    ordered.update(fields)
    return ordered


def item(
    obj: Item,
    library: Library,
    base_url: str,
    *,
    tags: list[tuple[str, int]],
    collections: list[str],
    num_children: int,
    parent_key: str | None = None,
    authors: Mapping[int, User] | None = None,
) -> dict[str, Any]:
    """Render an item in the API's envelope.

    Args:
        authors: The accounts this item's authorship points at, keyed by id.
            Passed in rather than looked up here, so a page of a hundred items
            costs one query instead of two hundred. Missing ids are simply not
            rendered, which is what upstream does for an account that has gone.
    """
    fields = ordered_fields(obj.item_type, obj.field_values())

    data: dict[str, Any] = {"key": obj.key, "version": obj.version, "itemType": obj.item_type}
    if parent_key:
        data["parentItem"] = parent_key
    data.update(fields)
    # An attachment's `mtime` is the one field value upstream serves as a
    # number: it keeps it in a column of its own, where altero keeps every
    # field as text. `Item.fromJSON` ignores it, so a plain sync never notices,
    # but `resolveConflicts` in the client's storage sync assigns it to
    # `attachmentSyncedModificationTime` -- whose setter throws "must be a
    # number" -- when a file conflict is settled in favour of the local copy.
    # Assigning in place rather than re-inserting, because the emitted order of
    # an attachment's fields is load-bearing (see `ordered_fields`).
    if str(data.get("mtime", "")).isdigit():
        data["mtime"] = int(data["mtime"])

    if obj.creators:
        data["creators"] = [
            {"creatorType": creator.creator_type, "name": creator.name}
            if creator.name is not None
            else {
                "creatorType": creator.creator_type,
                "firstName": creator.first_name or "",
                "lastName": creator.last_name or "",
            }
            for creator in obj.creators
        ]

    # A tag of the default (manual) type is written without its `type` key.
    data["tags"] = [
        {"tag": name} if type_ == 0 else {"tag": name, "type": type_} for name, type_ in tags
    ]
    data["collections"] = collections
    data["relations"] = render_relations(obj.relations)
    if obj.deleted:
        data["deleted"] = 1
    # Emitted only when true, as `deleted` is: otherwise every item in every
    # library would carry a property that concerns almost none of them.
    if obj.in_publications:
        data["inPublications"] = True
    data["dateAdded"] = timestamp(obj.date_added)
    data["dateModified"] = timestamp(obj.date_modified)

    meta: dict[str, Any] = {}
    if summary := creator_summary(obj.creators):
        meta["creatorSummary"] = summary
    if parsed := parsed_date(obj.sort_date):
        meta["parsedDate"] = parsed
    meta["numChildren"] = num_children
    meta.update(_authorship(obj, library, authors or {}))

    return {
        "key": obj.key,
        "version": obj.version,
        "library": library_block(library, base_url),
        "links": _object_links(library, base_url, "items", obj.key, parent_key),
        "meta": meta,
        "data": data,
    }


def collection(
    obj: Collection,
    library: Library,
    base_url: str,
    *,
    num_collections: int,
    num_items: int,
    parent_key: str | None = None,
) -> dict[str, Any]:
    """Render a collection in the API's envelope."""
    data: dict[str, Any] = {
        "key": obj.key,
        "version": obj.version,
        "name": obj.name,
        # A top-level collection reports `false` rather than omitting the key.
        "parentCollection": parent_key if parent_key else False,
        "relations": render_relations(obj.relations),
    }
    if obj.deleted:
        data["deleted"] = 1

    return {
        "key": obj.key,
        "version": obj.version,
        "library": library_block(library, base_url),
        "links": _object_links(library, base_url, "collections", obj.key, parent_key),
        "meta": {"numCollections": num_collections, "numItems": num_items},
        "data": data,
    }


def saved_search(obj: SavedSearch, library: Library, base_url: str) -> dict[str, Any]:
    """Render a saved search in the API's envelope."""
    data: dict[str, Any] = {
        "key": obj.key,
        "version": obj.version,
        "name": obj.name,
        "conditions": [
            {
                "condition": condition.condition,
                "operator": condition.operator,
                "value": condition.value,
            }
            for condition in obj.conditions
        ],
    }
    # As for items and collections: present only when the search is trashed.
    if obj.deleted:
        data["deleted"] = 1

    return {
        "key": obj.key,
        "version": obj.version,
        "library": library_block(library, base_url),
        "links": _object_links(library, base_url, "searches", obj.key),
        "meta": {},
        "data": data,
    }


def tag(
    name: str, tag_type: int, num_items: int, library: Library, base_url: str
) -> dict[str, Any]:
    """Render a tag in the API's envelope.

    A tag carries no version of its own here; clients read tag versions from
    ``format=versions``. Spaces in the name become ``+`` in the link, as upstream
    writes them.
    """
    prefix = f"{base_url}{library_prefix(library)}/tags"
    return {
        "tag": name,
        "links": {"self": json_link(f"{prefix}/{quote_plus(name)}")},
        "meta": {"type": tag_type, "numItems": num_items},
    }
