"""The set of routes the server exposes.

Restructuring a route module has twice silently dropped an endpoint, and under
PEP 649 a dependency annotation that no longer resolves does not raise — FastAPI
quietly treats the parameter as a missing query parameter and answers 400. This
inventory turns both failures into a red test.
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute, _IncludedRouter

#: Every endpoint, as (path, method). Library-scoped paths are listed once with
#: the /users prefix; each is also served under /groups.
EXPECTED = [
    ("/health", "GET"),
    # The web interface. Cookie-authenticated and deliberately outside the v3
    # API; see altero/api/routes/web.py.
    ("/web/config", "GET"),
    ("/web/auth/register", "POST"),
    ("/web/auth/login", "POST"),
    ("/web/auth/totp", "POST"),
    ("/web/auth/verify", "POST"),
    # Setting a password from a link an administrator issued. Answers without a
    # cookie, like the confirmation link: the token is the whole credential.
    ("/web/auth/forgot", "POST"),
    ("/web/auth/reset/{token}", "GET"),
    ("/web/auth/reset", "POST"),
    ("/web/auth/verify/resend", "POST"),
    ("/web/auth/session", "GET"),
    ("/web/auth/logout", "POST"),
    ("/web/account", "GET"),
    ("/web/account", "PATCH"),
    ("/web/account/locale", "PUT"),
    ("/web/account/locales", "GET"),
    ("/web/account/password", "POST"),
    ("/web/account/email", "POST"),
    ("/web/account/totp", "POST"),
    ("/web/account/totp/confirm", "POST"),
    ("/web/account/totp/disable", "POST"),
    ("/web/account/sessions/{session_id}", "DELETE"),
    ("/web/account/sessions/revoke-others", "POST"),
    ("/web/account/keys", "GET"),
    ("/web/account/keys", "POST"),
    ("/web/account/keys/{key_id}", "DELETE"),
    # The operator's own screens: what the instance costs and what state it is
    # in, for the one account that administers it rather than a library. Never
    # reachable with an API key -- see altero/api/routes/webadmin.py.
    ("/web/admin/overview", "GET"),
    ("/web/admin/storage", "GET"),
    ("/web/admin/storage/purge", "POST"),
    ("/web/admin/settings", "GET"),
    ("/web/admin/settings", "PUT"),
    ("/web/admin/retention/run", "POST"),
    # Account lifecycle: the operations that used to need a shell. The DELETE
    # is the one route under /web/admin that reaches into a library, and it
    # goes through the same clear_library a group deletion does.
    ("/web/admin/users", "GET"),
    ("/web/admin/users", "POST"),
    ("/web/admin/users/{user_id}", "PATCH"),
    ("/web/admin/users/{user_id}", "DELETE"),
    ("/web/admin/users/{user_id}/password", "POST"),
    ("/web/admin/users/{user_id}/revoke", "POST"),
    ("/web/admin/users/{user_id}/reset", "POST"),
    ("/web/link/{token}", "GET"),
    ("/web/link/{token}/approve", "POST"),
    ("/web/link/{token}/deny", "POST"),
    ("/web/notifications", "GET"),
    ("/web/notifications/{notification_id}/read", "POST"),
    ("/web/notifications/read-all", "POST"),
    ("/web/invitations/{invitation_id}/accept", "POST"),
    ("/web/invitations/{invitation_id}/decline", "POST"),
    ("/web/libraries/{library_id}/invitations", "GET"),
    ("/web/libraries/{library_id}/invitations", "POST"),
    ("/web/invitations/{invitation_id}", "DELETE"),
    ("/web/invitations/token/{token}", "GET"),
    ("/web/invitations/token/{token}/{decision}", "POST"),
    ("/web/groups", "GET"),
    ("/web/groups", "POST"),
    ("/web/groups/{library_id}", "GET"),
    ("/web/groups/{library_id}", "PATCH"),
    ("/web/groups/{library_id}", "DELETE"),
    ("/web/groups/{library_id}/activity", "GET"),
    ("/web/groups/{library_id}/notifications", "GET"),
    ("/web/groups/{library_id}/notifications", "PUT"),
    ("/web/groups/{library_id}/members", "GET"),
    ("/web/groups/{library_id}/members/{member_id}", "PUT"),
    ("/web/groups/{library_id}/members/{member_id}", "DELETE"),
    ("/web/groups/{library_id}/transfer", "POST"),
    ("/web/libraries", "GET"),
    ("/web/libraries/{library_id}/items", "GET"),
    ("/web/libraries/{library_id}/items/export", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}/children", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}/file", "GET"),
    ("/web/libraries/{library_id}/collections", "GET"),
    ("/web/libraries/{library_id}/tags", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}/citation", "GET"),
    # One collection made, renamed or moved, and one removed. See
    # altero/api/routes/webcollections.py.
    ("/web/libraries/{library_id}/collections", "POST"),
    ("/web/libraries/{library_id}/collections/{collection_key}", "PATCH"),
    ("/web/libraries/{library_id}/collections/{collection_key}", "DELETE"),
    # Items filed, trashed, deleted out of the trash, and copied into another
    # library -- a selection at a time, because that is what the reader picked
    # out. See altero/api/routes/webitems.py.
    ("/web/libraries/{library_id}/items", "PATCH"),
    ("/web/libraries/{library_id}/items", "DELETE"),
    ("/web/libraries/{library_id}/items/copy", "POST"),
    ("/web/libraries/{library_id}/trash", "DELETE"),
    # The one write about a single item: a version belongs to an item, and a
    # selection has no shared one. Same module; see its docstring.
    ("/web/libraries/{library_id}/items/{item_key}", "PATCH"),
    # An item put into My Publications on the desktop client's terms, and taken
    # out again with its children. Same module; see its docstring.
    ("/web/libraries/{library_id}/publications/items/{item_key}", "PUT"),
    ("/web/libraries/{library_id}/publications/items/{item_key}", "DELETE"),
    # One tag renamed, which is a write to every item carrying it and to
    # nothing else. See altero/api/routes/webtags.py.
    ("/web/libraries/{library_id}/tags/{tag_name}", "PATCH"),
    # A library read out of zotero.org and restored over this one. The only
    # endpoint whose work outlives its request. See
    # altero/api/routes/webmigrate.py.
    ("/web/migrate/zotero", "GET"),
    ("/web/migrate/zotero", "POST"),
    # A whole library out and a whole library back, which is a replacement
    # rather than an edit. See altero/api/routes/webtransfer.py.
    ("/web/libraries/{library_id}/archive", "GET"),
    ("/web/libraries/{library_id}/archive", "POST"),
    # A profile page: one person's published work, read by whoever their
    # setting allows -- including, by default, somebody with no account here.
    # The only endpoints under /web that answer without a cookie. See
    # altero/api/routes/webprofile.py.
    ("/web/profiles/{username}", "GET"),
    ("/web/profiles/{username}/items", "GET"),
    ("/web/profiles/{username}/items/{item_key}", "GET"),
    ("/web/profiles/{username}/items/{item_key}/children", "GET"),
    ("/web/profiles/{username}/items/{item_key}/file", "GET"),
    ("/web/profiles/{username}/items/{item_key}/citation", "GET"),
    # A link that shows one collection to whoever holds it. Making, changing
    # and revoking one takes a cookie, a CSRF token and write access to the
    # library; following one takes the token and nothing else, which makes
    # these the second set of endpoints under /web that answer without a
    # cookie. See altero/api/routes/webshares.py.
    ("/web/libraries/{library_id}/shares", "GET"),
    ("/web/libraries/{library_id}/collections/{collection_key}/shares", "POST"),
    ("/web/shares/{share_id}", "PATCH"),
    ("/web/shares/{share_id}", "DELETE"),
    ("/web/shared/{token}", "GET"),
    ("/web/shared/{token}/collections", "GET"),
    ("/web/shared/{token}/items", "GET"),
    ("/web/shared/{token}/items/{item_key}", "GET"),
    ("/web/shared/{token}/items/{item_key}/children", "GET"),
    ("/web/shared/{token}/items/{item_key}/file", "GET"),
    ("/web/shared/{token}/items/{item_key}/citation", "GET"),
    ("/web/schema", "GET"),
    ("/keys/{key}", "GET"),
    ("/keys/current", "GET"),
    ("/keys/current", "DELETE"),
    ("/keys/sessions", "POST"),
    ("/keys/sessions/{token}", "GET"),
    ("/keys/sessions/{token}", "DELETE"),
    ("/keys/sessions/{token}/login", "GET"),
    ("/users/{user_id}/groups", "GET"),
    ("/groups/{group_id}", "GET"),
    # Group administration. Upstream's paths, with an API key and a JSON body
    # where it wants a superuser and XML -- see docs/compatibility.md.
    ("/groups", "POST"),
    ("/groups/{group_id}", "PUT"),
    ("/groups/{group_id}", "PATCH"),
    ("/groups/{group_id}", "DELETE"),
    ("/groups/{group_id}/users", "GET"),
    ("/groups/{group_id}/users", "POST"),
    ("/groups/{group_id}/users/{member_id}", "PUT"),
    ("/groups/{group_id}/users/{member_id}", "DELETE"),
    ("/itemTypes", "GET"),
    ("/itemFields", "GET"),
    ("/itemTypeFields", "GET"),
    ("/itemTypeCreatorTypes", "GET"),
    ("/creatorFields", "GET"),
    ("/items/new", "GET"),
    ("/schema", "GET"),
    ("/storage/upload/{upload_key}", "POST"),
    # My Publications is a personal library only, so these have no /groups form.
    ("/users/{user_id}/publications/items", "GET"),
    ("/users/{user_id}/publications/items", "POST"),
    ("/users/{user_id}/publications/items", "PUT"),
    ("/users/{user_id}/publications/items", "DELETE"),
    ("/users/{user_id}/publications/items/top", "GET"),
    ("/users/{user_id}/publications/items/{item_key}", "GET"),
    ("/users/{user_id}/publications/settings", "GET"),
    ("/users/{user_id}/publications/deleted", "GET"),
]

#: Endpoints served under both /users/{user_id} and /groups/{group_id}.
LIBRARY_SCOPED = [
    ("/items", "GET"),
    ("/items", "POST"),
    ("/items", "DELETE"),
    ("/items/top", "GET"),
    ("/items/trash", "GET"),
    ("/items/tags", "GET"),
    ("/items/top/tags", "GET"),
    ("/items/trash/tags", "GET"),
    ("/items/{item_key}", "GET"),
    ("/items/{item_key}", "PUT"),
    ("/items/{item_key}", "PATCH"),
    ("/items/{item_key}", "DELETE"),
    ("/items/{item_key}/children", "GET"),
    ("/items/{item_key}/tags", "GET"),
    ("/items/{item_key}/file", "GET"),
    ("/items/{item_key}/file", "POST"),
    ("/items/{item_key}/file/content", "GET"),
    ("/items/{item_key}/file/view", "GET"),
    ("/items/{item_key}/fulltext", "GET"),
    ("/items/{item_key}/fulltext", "PUT"),
    ("/collections", "GET"),
    ("/collections", "POST"),
    ("/collections", "DELETE"),
    ("/collections/top", "GET"),
    ("/collections/{collection_key}", "GET"),
    ("/collections/{collection_key}", "PUT"),
    ("/collections/{collection_key}", "PATCH"),
    ("/collections/{collection_key}", "DELETE"),
    ("/collections/{collection_key}/collections", "GET"),
    ("/collections/{collection_key}/items", "GET"),
    ("/collections/{collection_key}/items/top", "GET"),
    ("/collections/{collection_key}/tags", "GET"),
    ("/collections/{collection_key}/items/tags", "GET"),
    ("/collections/{collection_key}/items/top/tags", "GET"),
    ("/searches", "GET"),
    ("/searches", "POST"),
    ("/searches", "DELETE"),
    ("/searches/{search_key}", "GET"),
    ("/searches/{search_key}", "PUT"),
    ("/searches/{search_key}", "PATCH"),
    ("/searches/{search_key}", "DELETE"),
    ("/tags", "GET"),
    ("/tags", "DELETE"),
    ("/tags/{tag_name}", "GET"),
    # Not upstream's; see docs/compatibility.md.
    ("/tags/{tag_name}", "PATCH"),
    ("/settings", "GET"),
    ("/settings", "POST"),
    ("/settings", "DELETE"),
    ("/settings/{name}", "GET"),
    ("/settings/{name}", "PUT"),
    ("/settings/{name}", "DELETE"),
    ("/deleted", "GET"),
    ("/fulltext", "GET"),
    ("/fulltext", "POST"),
]


def registered(app: FastAPI) -> set[tuple[str, str]]:
    """Return every (path, method) the application serves."""
    return {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def expected() -> set[tuple[str, str]]:
    every = set(EXPECTED)
    for path, method in LIBRARY_SCOPED:
        every.add((f"/users/{{user_id}}{path}", method))
        every.add((f"/groups/{{group_id}}{path}", method))
    return every


def test_every_expected_route_is_registered(app: FastAPI) -> None:
    missing = expected() - registered(app)

    assert not missing, f"routes disappeared: {sorted(missing)}"


def test_no_unexpected_routes_appeared(app: FastAPI) -> None:
    # Keeps this list honest: a new endpoint has to be declared here too.
    documented = expected()
    extra = {
        (path, method)
        for path, method in registered(app)
        if (path, method) not in documented and not path.startswith(("/openapi", "/docs", "/redoc"))
    }

    assert not extra, f"undeclared routes: {sorted(extra)}"


def test_scoped_tag_routes_precede_the_item_key_route(app: FastAPI) -> None:
    """`/items/top/tags` must be matched before `/items/{item_key}/tags`.

    Registered the other way round, `top` and `trash` are read as item keys and
    the scoped listings become 404s.
    """
    paths = [route.path for route in registered_in_order(app)]

    specific = paths.index("/users/{user_id}/items/top/tags")
    generic = paths.index("/users/{user_id}/items/{item_key}/tags")

    assert specific < generic


def registered_in_order(app: FastAPI) -> list[APIRoute]:
    """Return every route in the order it will be matched.

    Included routers are wrapped, so the originals have to be unwrapped to see
    the order within each.
    """
    routes: list[APIRoute] = []
    for entry in app.routes:
        if isinstance(entry, APIRoute):
            routes.append(entry)
        elif isinstance(entry, _IncludedRouter):
            routes.extend(
                route for route in entry.original_router.routes if isinstance(route, APIRoute)
            )
    return routes
