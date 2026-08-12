"""The Netscape bookmark file every browser still imports.

A port of `Bookmarks.js`. An item with no URL is not a bookmark and is left
out, whatever type it is -- which is why this format skips nothing by type: a
snapshot attachment has a URL and is exactly the thing somebody exporting
bookmarks is after.

One deliberate difference from upstream: the title and the URL are escaped.
The translator writes both straight into the markup, so a title containing an
ampersand or an angle bracket produces a file no HTML parser reads back the way
it went in -- and this server will answer `format=bookmarks` to a browser with
an API key in the query string, where unescaped markup is not merely untidy.
"""

from collections.abc import Sequence

from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter

_HEADER = (
    "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n"
    "<!-- This is an automatically generated file.\n"
    "     It will be read and overwritten.\n"
    "     DO NOT EDIT! -->\n"
    '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
    "<TITLE>Bookmarks</TITLE>\n"
    "<H1>Bookmarks Menu</H1>\n"
    "<DL>\n"
)

_ESCAPES = {"&": "&amp;", '"': "&quot;", "<": "&lt;", ">": "&gt;"}


def _escape(value: str) -> str:
    return "".join(_ESCAPES.get(character, character) for character in value)


class Bookmarks(TextWriter):
    """A Netscape bookmark file."""

    #: Anything with a URL is a bookmark, an attachment's snapshot included.
    skips = frozenset()

    def begin(self) -> str:
        return _HEADER

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "".join(self._entry(item) for item in items if item.get("url"))

    def _entry(self, item: ExportItem) -> str:
        tags = ",".join(item.tag_names)
        attributes = f' TAGS="{_escape(tags)}"' if tags else ""
        return (
            f'    <DT><A HREF="{_escape(item.get("url"))}"{attributes}>'
            f"{_escape(item.get('title'))}</A>\n"
        )

    def end(self) -> str:
        return "</DL>"
