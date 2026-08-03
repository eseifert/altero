"""Rendering of domain objects into the API's JSON shapes.

Like the service layer, this module is free of web-framework imports: callers
supply the base URL and receive plain dictionaries.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote_plus

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


def group(library: Library, group: Group, base_url: str) -> dict[str, Any]:
    """Render a group library.

    ``meta`` is not emitted yet: its ``created``, ``lastModified`` and
    ``numItems`` values need object timestamps that do not exist so far.
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
            "libraryEditing": group.library_editing,
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
        "access": access,
    }


def _timestamp(value: datetime) -> str:
    """Render a stored timestamp as the UTC form the API uses."""
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


def item(
    obj: Item,
    library: Library,
    base_url: str,
    *,
    tags: list[tuple[str, int]],
    collections: list[str],
    num_children: int,
    parent_key: str | None = None,
) -> dict[str, Any]:
    """Render an item in the API's envelope."""
    fields = obj.field_values()

    data: dict[str, Any] = {"key": obj.key, "version": obj.version, "itemType": obj.item_type}
    if parent_key:
        data["parentItem"] = parent_key
    data.update(fields)

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
    data["dateAdded"] = _timestamp(obj.date_added)
    data["dateModified"] = _timestamp(obj.date_modified)

    meta: dict[str, Any] = {}
    if summary := creator_summary(obj.creators):
        meta["creatorSummary"] = summary
    if parsed := parsed_date(obj.sort_date):
        meta["parsedDate"] = parsed
    meta["numChildren"] = num_children

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
