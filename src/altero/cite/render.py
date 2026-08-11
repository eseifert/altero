"""Rendering CSL JSON as a bibliography or a citation.

Upstream posts the CSL JSON to a citation server running citeproc-js and then
re-styles the HTML that comes back. There is no citation server here, so the
same two steps happen in process: :mod:`citeproc` produces the entries, and the
wrapper markup below reproduces what the reference implementation adds around
them -- line height, hanging indent and entry spacing read from the style, as
the desktop client's own ``makeFormattedBibliography`` does.

Rendering runs on the event loop rather than in a worker thread on purpose: a
parsed style is cached and reused, and citeproc-py hangs the output formatter
off that shared style, so two renders must not overlap.
"""

import html
import re
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

#: Exactly two full stops, as an initialled name followed by a style's own
#: sentence-ending period produces. Three are left alone: that is an ellipsis a
#: style put there deliberately.
_DOUBLED_PERIOD = re.compile(r"(?<!\.)\.\.(?!\.)")


@lru_cache(maxsize=32)
def _style(name: str, locale: str) -> Any:
    """Return the parsed style, kept for reuse across requests.

    Parsing a style is tens of milliseconds and the same handful are asked for
    over and over, so they are cached. Validation is off: the styles come from
    the CSL repository, and validating each one needs the RNC schema toolchain.
    """
    from citeproc import CitationStylesStyle

    return CitationStylesStyle(style_path(name), locale=locale, validate=False)


def _tidy(markup: str) -> str:
    """Collapse the doubled full stop a style's own period adds after initials.

    citeproc-js drops one of the two; citeproc-py emits both, so ``Doe, J.``
    followed by a sentence-ending period reads ``Doe, J...``. Only text outside
    tags is touched, so an attribute value cannot be rewritten.
    """
    return _TEXT_OUTSIDE_TAGS.sub(
        lambda match: (
            match.group(1)
            if match.group(1) is not None
            else _DOUBLED_PERIOD.sub(".", match.group(2))
        ),
        markup,
    )


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


def _finish(markup: str, linkwrap: bool) -> str:
    """Apply the post-processing every rendered result gets."""
    markup = _tidy(markup)
    return _linkwrap(markup) if linkwrap else markup


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
        return _finish(markup, linkwrap)

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

    return _finish("\n".join(lines), linkwrap)


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
    return _finish(f"<span>{text}</span>", linkwrap)
