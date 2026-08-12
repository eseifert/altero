"""Simple Evernote export: one `<note>` per item, in an ENEX file.

A port of `Evernote.js`. The format is a note-taking application's, not a
bibliography's, so what survives the trip is the title, the dates, the tags and
the address the item came from -- an item exports as an empty note with its
metadata attached, which is what upstream produces too.

Three of the translator's habits are not copied, all three for the same reason:
they write something that is not what it says it is.

- The title is escaped once. Upstream escapes `<` and then escapes every `&`
  again over the whole document, so a title with an angle bracket in it arrives
  in Evernote reading `&lt;` in full.
- The note body is left alone inside its CDATA section. That second pass
  escapes the ampersands in there as well, and CDATA is exactly the thing that
  does not need escaping.
- `<updated>` ends in one `Z` and an item with no URL has an empty
  `<source-url>`. Upstream writes `ZZ` -- it appends a `Z` to a timestamp that
  already has one -- and the string `undefined` for the URL.
"""

from collections.abc import Sequence
from xml.sax.saxutils import escape

from altero import __version__
from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter

#: Evernote's own limits, which the translator cuts values to rather than
#: letting the import fail on them.
_TITLE_LIMIT = 252
_TAG_LIMIT = 95

_HEADER = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    "<!DOCTYPE en-export SYSTEM 'http://xml.evernote.com/pub/evernote-export.dtd'>\n"
    f"<en-export application='altero' version='{__version__}'>\n"
)

_BODY = (
    "        <![CDATA[<?xml version='1.0' encoding='UTF-8'?>"
    "<!DOCTYPE en-note SYSTEM 'http://xml.evernote.com/pub/enml2.dtd'>\n"
    "        <en-note>\n"
    "        </en-note>]]>\n"
)


def _clipped(value: str, limit: int) -> str:
    return f"{value[:limit]}..." if len(value) > limit else value


def _stamp(value: str) -> str:
    """Return a stored timestamp as Evernote writes one: `20160913T111712Z`."""
    if not value:
        return ""
    return value.replace("-", "").replace(":", "").replace(" ", "T").rstrip("Z") + "Z"


class Evernote(TextWriter):
    """An ENEX file."""

    #: Every item becomes a note, a note item included -- which upstream titles
    #: `[Untitled]` and exports the metadata of rather than the text.
    skips = frozenset()

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "".join(self._entry(item) for item in items)

    def _entry(self, item: ExportItem) -> str:
        title = _clipped(item.get("title") or "[Untitled]", _TITLE_LIMIT)
        lines = [
            "<note>\n",
            f"    <title>{escape(title)}</title>\n",
            "    <content>\n",
            _BODY,
            "    </content>\n",
            f"    <created>{_stamp(item.date_added)}</created>\n",
            f"    <updated>{_stamp(item.date_modified)}</updated>\n",
        ]
        for name, _ in item.tags:
            # A comma separates one tag from the next in Evernote, so a tag
            # carrying one is rewritten rather than split in two on import.
            tag = _clipped(" / ".join(part.strip() for part in name.split(",")), _TAG_LIMIT)
            lines.append(f"    <tag>{escape(tag)}</tag>\n")

        lines += [
            "    <note-attributes>\n",
            "        <source>web.clip</source>\n",
            f"        <source-url>{escape(item.get('url'))}</source-url>\n",
            "    </note-attributes>\n",
            "</note>\n",
        ]
        return "".join(lines)

    def begin(self) -> str:
        return _HEADER

    def end(self) -> str:
        return "</en-export>\n"
