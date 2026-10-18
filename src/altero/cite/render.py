"""Rendering CSL JSON as a bibliography or a citation.

Upstream posts the CSL JSON to a citation server running citeproc-js and then
re-styles the HTML that comes back. There is no citation server here, so the
same two steps happen in process: :mod:`citeproc` produces the entries, and the
wrapper markup below reproduces what the reference implementation adds around
them -- line height, hanging indent and entry spacing read from the style, as
the desktop client's own ``makeFormattedBibliography`` does.

Rendering takes tens of milliseconds an item, so it runs on one dedicated
worker thread rather than on the event loop, where a page of a hundred froze
every other request for seconds. One thread and no more: a parsed style is
cached and reused, and citeproc-py hangs the output formatter off that shared
style, so two renders must not overlap. :func:`render_entries` and
:func:`render_bibliography` are the way in; the functions they wrap are for the
worker and for tests.

What comes out is decided entirely by the CSL JSON and the three options, so
it is remembered by exactly those: an item rendered again unchanged is not
rendered again, and an item that changed is different JSON.
"""

import asyncio
import html
import json
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

from .styles import DEFAULT_LOCALE, DEFAULT_STYLE, style_path

#: Smallest line height the reference implementation will emit, whatever the
#: style asks for.
_MIN_LINE_SPACING = 1.35

#: Indent applied to a style that asks for a hanging indent. CSL 1.0.1 states it
#: as a flag; this is the width the client turns that flag into.
_HANGING_INDENT_EM = 2

#: A bare URL in rendered output, for `linkwrap`.
_URL = re.compile(r"(?<![\"'>=])\bhttps?://[^\s<>\"']+[^\s<>\"'.,;:)\]]")

#: Text outside of a tag, which is the only place a link may be introduced.
_TEXT_OUTSIDE_TAGS = re.compile(r"(<[^>]*>)|([^<]+)")


@lru_cache(maxsize=32)
def _style(name: str, locale: str) -> Any:
    """Return the parsed style, kept for reuse across requests.

    Parsing a style is tens of milliseconds and the same handful are asked for
    over and over, so they are cached. Validation is off: the styles come from
    the CSL repository, and validating each one needs the RNC schema toolchain.
    """
    from citeproc import CitationStylesStyle

    return CitationStylesStyle(style_path(name), locale=locale, validate=False)


def _bibliography_options(style: Any) -> tuple[float, int, bool]:
    """Return the line spacing, entry spacing and hanging indent of a style."""
    element = style.root.find("{*}bibliography")
    if element is None:
        return _MIN_LINE_SPACING, 1, False

    def number(name: str, default: float) -> float:
        try:
            return float(element.get(name, default))
        except TypeError, ValueError:
            return default

    line_spacing = max(number("line-spacing", 1), _MIN_LINE_SPACING)
    entry_spacing = int(number("entry-spacing", 1))
    hanging_indent = element.get("hanging-indent") == "true"
    return line_spacing, entry_spacing, hanging_indent


def _linkwrap(markup: str) -> str:
    """Wrap bare URLs in the rendered output in anchors.

    Only text outside tags is touched, so a URL that a style already rendered as
    a link is left as it is.
    """

    def wrap(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            return match.group(1)
        return _URL.sub(
            lambda url: f'<a href="{html.escape(url.group(0), quote=True)}">{url.group(0)}</a>',
            match.group(2),
        )

    return _TEXT_OUTSIDE_TAGS.sub(wrap, markup)


def _render(items: list[dict[str, Any]], style_name: str, locale: str) -> tuple[Any, list[Any]]:
    """Register ``items`` against a style and return the bibliography and cites."""
    from citeproc import Citation, CitationItem, CitationStylesBibliography, formatter
    from citeproc.source.json import CiteProcJSON

    style = _style(style_name, locale)
    bibliography = CitationStylesBibliography(style, CiteProcJSON(items), formatter.html)

    citations = [Citation([CitationItem(item["id"])]) for item in items]
    for citation in citations:
        bibliography.register(citation)
    return bibliography, citations


def bibliography(
    items: list[dict[str, Any]],
    *,
    style: str = DEFAULT_STYLE,
    locale: str = DEFAULT_LOCALE,
    linkwrap: bool = False,
) -> str:
    """Return ``items`` as an HTML bibliography.

    A style that defines no bibliography -- some numeric styles do not -- falls
    back to an ordered list of citations, which is what upstream does when the
    citation server returns nothing.
    """
    if not items:
        return ""

    rendered, citations = _render(items, style, locale)

    if not rendered.style.has_bibliography():
        entries = [str(rendered.cite(citation, lambda _: None)) for citation in citations]
        markup = "<ol>\n\t<li>" + "</li>\n\t<li>".join(entries) + "</li>\n</ol>"
        return _linkwrap(markup) if linkwrap else markup

    rendered.sort()
    entries = [str(entry) for entry in rendered.bibliography()]

    line_spacing, entry_spacing, hanging_indent = _bibliography_options(rendered.style)
    body_style = f"line-height: {line_spacing:g}; "
    if hanging_indent:
        body_style += f"padding-left: {_HANGING_INDENT_EM}em; text-indent:-{_HANGING_INDENT_EM}em;"

    lines = [f'<div class="csl-bib-body" style="{body_style}">']
    for position, entry in enumerate(entries):
        spacing = (
            f' style="margin-bottom: {entry_spacing}em;"'
            if entry_spacing and position < len(entries) - 1
            else ""
        )
        lines.append(f'  <div class="csl-entry"{spacing}>{entry}</div>')
    lines.append("</div>")

    markup = "\n".join(lines)
    return _linkwrap(markup) if linkwrap else markup


def citation(
    item: dict[str, Any],
    *,
    style: str = DEFAULT_STYLE,
    locale: str = DEFAULT_LOCALE,
    linkwrap: bool = False,
) -> str:
    """Return one item's in-text citation, in the span upstream wraps it in."""
    rendered, citations = _render([item], style, locale)
    text = str(rendered.cite(citations[0], lambda _: None))
    markup = f"<span>{text}</span>"
    return _linkwrap(markup) if linkwrap else markup


#: The one thread every render runs on. See the module docstring.
_RENDERER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="altero-cite")

#: How many rendered entries are remembered. An entry is a few hundred bytes.
CACHE_SIZE = 4096


@lru_cache(maxsize=CACHE_SIZE)
def _bibliography_of(payload: str, style: str, locale: str, linkwrap: bool) -> str:
    return bibliography(json.loads(payload), style=style, locale=locale, linkwrap=linkwrap)


@lru_cache(maxsize=CACHE_SIZE)
def _citation_of(payload: str, style: str, locale: str, linkwrap: bool) -> str:
    return citation(json.loads(payload), style=style, locale=locale, linkwrap=linkwrap)


def _key(value: Any) -> str:
    """The JSON a render is remembered by: the same item always reads the same."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _entries(
    payloads: list[str], bib: bool, cite: bool, style: str, locale: str, linkwrap: bool
) -> list[tuple[str | None, str | None]]:
    return [
        (
            _bibliography_of(f"[{payload}]", style, locale, linkwrap) if bib else None,
            _citation_of(payload, style, locale, linkwrap) if cite else None,
        )
        for payload in payloads
    ]


async def render_entries(
    items: Sequence[dict[str, Any]],
    *,
    bib: bool = True,
    cite: bool = True,
    style: str = DEFAULT_STYLE,
    locale: str = DEFAULT_LOCALE,
    linkwrap: bool = False,
) -> list[tuple[str | None, str | None]]:
    """Return each item's own bibliography entry and in-text citation, in order.

    ``None`` stands for whichever of the two was not asked for. One trip to the
    renderer for the lot, so a page of them waits behind no other request's
    renders but its own.
    """
    payloads = [_key(item) for item in items]
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _RENDERER, _entries, payloads, bib, cite, style, locale, linkwrap
    )


async def render_bibliography(
    items: Sequence[dict[str, Any]],
    *,
    style: str = DEFAULT_STYLE,
    locale: str = DEFAULT_LOCALE,
    linkwrap: bool = False,
) -> str:
    """Return ``items`` as one HTML bibliography, as :func:`bibliography` does."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _RENDERER, _bibliography_of, _key(list(items)), style, locale, linkwrap
    )
