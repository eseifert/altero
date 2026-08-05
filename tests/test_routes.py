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
    ("/web/groups/{library_id}/members", "GET"),
    ("/web/groups/{library_id}/members/{member_id}", "PUT"),
    ("/web/groups/{library_id}/members/{member_id}", "DELETE"),
    ("/web/groups/{library_id}/transfer", "POST"),
    ("/web/libraries", "GET"),
    ("/web/libraries/{library_id}/items", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}/children", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}/file", "GET"),
    ("/web/libraries/{library_id}/collections", "GET"),
    ("/web/libraries/{library_id}/tags", "GET"),
    ("/web/libraries/{library_id}/items/{item_key}/citation", "GET"),
    # A whole library out and a whole library back: the only endpoint under
    # /web that writes to one. See altero/api/routes/webtransfer.py.
    ("/web/libraries/{library_id}/archive", "GET"),
    ("/web/libraries/{library_id}/archive", "POST"),
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
