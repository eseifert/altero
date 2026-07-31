"""Result pagination and the ``Link`` response header."""

from collections.abc import Sequence
from urllib.parse import urlencode

#: Number of results returned when the client does not ask for a specific count.
DEFAULT_LIMIT = 25

#: Largest number of results the server will return in one response.
MAX_LIMIT = 100

#: Smallest number of results the server will return in one response.
MIN_LIMIT = 1


def clamp_limit(limit: int | None) -> int:
    """Return a usable page size for a client-supplied ``limit``.

    Out-of-range values are clamped rather than rejected, so that a client asking
    for more than the server is willing to return still gets results.
    """
    if limit is None:
        return DEFAULT_LIMIT
    return max(MIN_LIMIT, min(limit, MAX_LIMIT))


def _page_url(base_url: str, query: Sequence[tuple[str, str]], start: int, limit: int) -> str:
    """Return ``base_url`` with ``start`` and ``limit`` replaced, other parameters kept."""
    preserved = [(name, value) for name, value in query if name not in {"start", "limit"}]
    return f"{base_url}?{urlencode([*preserved, ('limit', limit), ('start', start)])}"


def build_page_links(
    base_url: str,
    query: Sequence[tuple[str, str]],
    start: int,
    limit: int,
    total: int,
) -> dict[str, str]:
    """Return the ``rel`` links describing the result set around the current page.

    Backward links are omitted on the first page and forward links on the last,
    matching the API's behaviour.

    Args:
        base_url: Request URL without its query string.
        query: The request's query parameters as pairs, so that repeated
            parameters such as ``tag`` survive into the generated links.
        start: Index of the first result on the current page.
        limit: Page size.
        total: Total number of matching results.
    """
    links: dict[str, str] = {}

    if start > 0:
        links["first"] = _page_url(base_url, query, 0, limit)
        links["prev"] = _page_url(base_url, query, max(0, start - limit), limit)

    if total > 0 and start + limit < total:
        links["next"] = _page_url(base_url, query, start + limit, limit)
        # Start index of the final page, which may hold fewer than `limit` results.
        links["last"] = _page_url(base_url, query, ((total - 1) // limit) * limit, limit)

    return links


def format_link_header(links: dict[str, str]) -> str:
    """Render ``links`` as an RFC 8288 ``Link`` header value."""
    return ", ".join(f'<{url}>; rel="{rel}"' for rel, url in links.items())
