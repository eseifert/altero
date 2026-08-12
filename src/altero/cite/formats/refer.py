"""Refer/BibIX, the tagged format `refer` and BibIX read.

A port of `Refer_BibIX.js`. Two things about it are worth knowing before
changing anything:

The order the tags come out in is the order JavaScript walks the translator's
`fieldMap` object in, which is not the order it is written in: a key that looks
like a number comes first. `%7`, the edition, is therefore emitted before the
title, and :data:`_FIELDS` is written in the order that produces.

Lines end in CRLF, including the ones inside a `%K` list of tags, and a blank
line separates one item from the next.
"""

from collections.abc import Sequence

from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter

#: Refer tag to item field, in the order the translator emits them.
_FIELDS = (
    ("7", "edition"),
    ("T", "title"),
    ("S", "series"),
    ("V", "volume"),
    ("N", "issue"),
    ("C", "place"),
    ("I", "publisher"),
    ("R", "type"),
    ("P", "pages"),
    ("W", "archiveLocation"),
    ("*", "rights"),
    ("@", "ISBN"),
    ("L", "callNumber"),
    ("M", "accessionNumber"),
    ("U", "url"),
    ("X", "abstractNote"),
    ("G", "language"),
)

#: Item type to the reference type written as `%0`. Anything absent is
#: `Generic`, which is what the translator falls back to.
_TYPES = {
    "book": "Book",
    "bookSection": "Book Section",
    "journalArticle": "Journal Article",
    "magazineArticle": "Magazine Article",
    "newspaperArticle": "Newspaper Article",
    "thesis": "Thesis",
    "letter": "Personal Communication",
    "manuscript": "Unpublished Work",
    "interview": "Personal Communication",
    "film": "Film or Broadcast",
    "artwork": "Artwork",
    "webpage": "Web Page",
    "report": "Report",
    "bill": "Bill",
    "case": "Case",
    "hearing": "Hearing",
    "patent": "Patent",
    "statute": "Statute",
    "email": "Personal Communication",
    "map": "Map",
    "blogPost": "Web Page",
    "instantMessage": "Personal Communication",
    "forumPost": "Web Page",
    "audioRecording": "Audiovisual Material",
    "presentation": "Report",
    "videoRecording": "Audiovisual Material",
    "tvBroadcast": "Film or Broadcast",
    "radioBroadcast": "Film or Broadcast",
    "podcast": "Audiovisual Material",
    "computerProgram": "Computer Program",
    "conferencePaper": "Conference Paper",
    "document": "Generic",
    "encyclopediaArticle": "Encyclopedia",
    "dictionaryEntry": "Dictionary",
}

#: The tag each creator type is written under. A translator gets `%?`, which is
#: not a Refer tag at all -- the translator has written it that way since it was
#: first committed, and an importer that meets one ignores the line.
_CREATOR_TAGS = {"editor": "E", "translator": "?"}

_BREAK = "\r\n"


def _tag(tag: str, value: str) -> str:
    """Return one tagged line, or nothing at all when the value is empty."""
    return f"%{tag} {value}{_BREAK}" if value else ""


class Refer(TextWriter):
    """Refer/BibIX."""

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "".join(self._entry(item) for item in items)

    def _entry(self, item: ExportItem) -> str:
        lines = [_tag("0", _TYPES.get(item.item_type, "Generic"))]
        lines += [_tag(tag, item.get(field)) for tag, field in _FIELDS]

        # A journal's title is `%J` and everything else's container is `%B`.
        if container := item.get("publicationTitle"):
            lines.append(_tag("J" if item.item_type == "journalArticle" else "B", container))

        lines += [
            _tag(_CREATOR_TAGS.get(creator.creator_type, "A"), creator.name)
            for creator in item.creators
        ]
        lines.append(_tag("D", item.get("date")))
        lines.append(_tag("K", _BREAK.join(item.tag_names)))
        return "".join(lines) + _BREAK
