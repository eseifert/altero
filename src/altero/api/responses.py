"""Construction of listing responses.

Every listing endpoint answers with the same headers and supports the same three
formats, so the logic lives here rather than in each route.
"""

from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from altero.pagination import build_page_links, format_link_header
from altero.query import Format, ListQuery

#: Content types of the formats that are not JSON. A bibliography is a document
#: to display; CSL JSON has a media type of its own that citation tooling looks
#: for.
CONTENT_TYPES: dict[Format, str] = {
    Format.BIB: "text/html; charset=UTF-8",
    Format.CSLJSON: "application/vnd.citationstyles.csl+json",
    Format.BIBTEX: "application/x-bibtex",
    Format.BIBLATEX: "application/x-bibtex",
    Format.RIS: "application/x-research-info-systems",
}


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
    csljson: list[Any] | None = None,
    bibliography: str | None = None,
    exported: str | None = None,
) -> Response:
    """Render a page of results in the format the client asked for.

    Args:
        objects: Fully serialized objects, used by ``format=json``.
        keys: Object keys, used by ``format=keys``.
        versions: Key-to-version mapping, used by ``format=versions``.
        csljson: CSL JSON objects, used by ``format=csljson``.
        bibliography: Rendered HTML, used by ``format=bib``.
        exported: A written file, used by the export formats.
    """
    headers = library_headers(version, total)

    # A bibliography is one document rather than a page of results, so it
    # carries no paging links. Upstream leaves them off for the same reason.
    if query.response_format is not Format.BIB:
        base_url = str(request.url).split("?")[0]
        links = build_page_links(base_url, list(query.raw), query.start, query.limit, total)
        if link_header := format_link_header(links):
            headers["Link"] = link_header

    if query.response_format is Format.KEYS:
        # One key per line, which is what the API returns for this format.
        return PlainTextResponse("\n".join(keys), headers=headers)

    if query.response_format is Format.VERSIONS:
        return JSONResponse(versions, headers=headers)

    if query.response_format is Format.CSLJSON:
        return JSONResponse(
            {"items": csljson or []},
            headers=headers,
            media_type=CONTENT_TYPES[Format.CSLJSON],
        )

    if query.response_format is Format.BIB:
        return HTMLResponse(bibliography or "", headers=headers)

    if content_type := CONTENT_TYPES.get(query.response_format):
        return PlainTextResponse(exported or "", headers=headers, media_type=content_type)

    return JSONResponse(objects, headers=headers)


def object_response(payload: Any, version: int, response_format: Format = Format.JSON) -> Response:
    """Render a single object with the headers describing its library."""
    headers = library_headers(version)

    if response_format is Format.CSLJSON:
        # Upstream wraps a single item in the same `items` array a listing uses,
        # with a note in its source that this is what it would change in v4.
        return JSONResponse(
            {"items": [payload]}, headers=headers, media_type=CONTENT_TYPES[Format.CSLJSON]
        )
    if response_format is Format.BIB:
        return HTMLResponse(str(payload), headers=headers)
    if content_type := CONTENT_TYPES.get(response_format):
        return PlainTextResponse(str(payload), headers=headers, media_type=content_type)
    return JSONResponse(payload, headers=headers)
