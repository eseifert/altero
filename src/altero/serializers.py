"""Rendering of domain objects into the API's JSON shapes.

Like the service layer, this module is free of web-framework imports: callers
supply the base URL and receive plain dictionaries.
"""

from typing import Any

from altero.models import ApiKey, Group, Library, LibraryType, User

#: Path segment used in URLs for each library type.
_PREFIX = {LibraryType.USER: "users", LibraryType.GROUP: "groups"}


def library_prefix(library: Library) -> str:
    """Return the ``/users/<id>`` or ``/groups/<id>`` prefix for ``library``."""
    return f"/{_PREFIX[library.type]}/{library.owner_id}"


def json_link(href: str) -> dict[str, str]:
    return {"href": href, "type": "application/json"}


def library_block(library: Library, base_url: str) -> dict[str, Any]:
    """Return the ``library`` block embedded in every object response."""
    return {
        "type": library.type.value,
        "id": library.owner_id,
        "name": library.name,
        "links": {"self": json_link(f"{base_url}{library_prefix(library)}")},
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
