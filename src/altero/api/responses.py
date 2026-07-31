"""Construction of listing responses.

Every listing endpoint answers with the same headers and supports the same three
formats, so the logic lives here rather than in each route.
"""

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from altero.pagination import build_page_links, format_link_header
from altero.query import Format, ListQuery


def library_headers(version: int, total: int | None = None) -> dict[str, str]:
    """Return the headers reported for a library's contents."""
    headers = {"Last-Modified-Version": str(version)}
    if total is not None:
        headers["Total-Results"] = str(total)
    return headers


def not_modified(request: Request, version: int) -> Response | None:
    """Return a 304 when the client already has this version of the library.

    The API reuses ``If-Modified-Since-Version`` for this rather than the
    timestamp-based conditional headers.
    """
    supplied = request.headers.get("If-Modified-Since-Version")
    if supplied is None:
        return None

    try:
        known = int(supplied)
    except ValueError:
        return None

    if version <= known:
        return Response(status_code=304, headers=library_headers(version))
    return None


def listing_response(
    request: Request,
    query: ListQuery,
    *,
    version: int,
    total: int,
    objects: list[Any],
    keys: list[str],
    versions: dict[str, int],
) -> Response:
    """Render a page of results in the format the client asked for.

    Args:
        objects: Fully serialized objects, used by ``format=json``.
        keys: Object keys, used by ``format=keys``.
        versions: Key-to-version mapping, used by ``format=versions``.
    """
    headers = library_headers(version, total)

    base_url = str(request.url).split("?")[0]
    links = build_page_links(base_url, list(query.raw), query.start, query.limit, total)
    if link_header := format_link_header(links):
        headers["Link"] = link_header

    if query.response_format is Format.KEYS:
        # One key per line, which is what the API returns for this format.
        return PlainTextResponse("\n".join(keys), headers=headers)

    if query.response_format is Format.VERSIONS:
        return JSONResponse(versions, headers=headers)

    return JSONResponse(objects, headers=headers)


def object_response(payload: Any, version: int) -> Response:
    """Render a single object with the headers describing its library."""
    return JSONResponse(payload, headers=library_headers(version))
