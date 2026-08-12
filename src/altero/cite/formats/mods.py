"""MODS, the Library of Congress's bibliographic schema.

A port of `MODS.js`. What decides the shape of a record is whether the item is
*partial* -- an article, a chapter, a post: something published inside something
else. A partial item's `<mods>` describes the piece and a `<relatedItem
type="host">` describes what it appeared in, and it is the host that carries the
journal's title, its ISSN, the volume and the page range. Everything else is
described by the `<mods>` alone.

Two of the translator's dead ends are kept rather than corrected, because a
record that gained a field here would not be the record a MODS consumer has
been reading:

- A conference name is built and never attached, so it does not appear.
- An item with a distributor and no publisher writes neither: the translator
  reaches for `item.publisher` in both branches.
"""

import re
from collections.abc import Sequence

from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter
from altero.cite.formats.xmlwriter import Builder, Element

MODS_NAMESPACE = "http://www.loc.gov/mods/v3"

#: Item types that describe something published inside something else.
_PARTIAL = frozenset(
    {
        "blogPost",
        "bookSection",
        "conferencePaper",
        "dictionaryEntry",
        "encyclopediaArticle",
        "forumPost",
        "journalArticle",
        "magazineArticle",
        "newspaperArticle",
        "webpage",
    }
)

#: Item type to what MODS calls that kind of thing.
_RESOURCE_TYPES = {
    "artwork": "still image",
    "audioRecording": "sound recording",
    "bill": "text",
    "blogPost": "software, multimedia",
    "book": "text",
    "bookSection": "text",
    "case": "text",
    "computerProgram": "software, multimedia",
    "conferencePaper": "text",
    "dictionaryEntry": "text",
    "document": "text",
    "email": "text",
    "encyclopediaArticle": "text",
    "film": "moving image",
    "forumPost": "text",
    "hearing": "text",
    "instantMessage": "text",
    "interview": "text",
    "journalArticle": "text",
    "letter": "text",
    "magazineArticle": "text",
    "manuscript": "text",
    "map": "cartographic",
    "newspaperArticle": "text",
    "patent": "text",
    "podcast": "sound recording-nonmusical",
    "presentation": "mixed material",
    "radioBroadcast": "sound recording-nonmusical",
    "report": "text",
    "statute": "text",
    "thesis": "text",
    "tvBroadcast": "moving image",
    "videoRecording": "moving image",
    "webpage": "software, multimedia",
}

#: Item type to the MARC genre term. Several types have none -- a computer
#: program, a document, a manuscript, a presentation and a television broadcast
#: -- and the translator leaves them commented out rather than guessing.
_MARC_GENRES = {
    "artwork": "art original",
    "audioRecording": "sound",
    "bill": "legislation",
    "blogPost": "web site",
    "book": "book",
    "bookSection": "book",
    "case": "legal case and case notes",
    "conferencePaper": "conference publication",
    "dictionaryEntry": "dictionary",
    "email": "letter",
    "encyclopediaArticle": "encyclopedia",
    "film": "motion picture",
    "forumPost": "web site",
    "hearing": "government publication",
    "instantMessage": "letter",
    "interview": "interview",
    "journalArticle": "journal",
    "letter": "letter",
    "magazineArticle": "periodical",
    "map": "map",
    "newspaperArticle": "newspaper",
    "patent": "patent",
    "podcast": "speech",
    "radioBroadcast": "sound",
    "report": "technical report",
    "statute": "legislation",
    "thesis": "thesis",
    "videoRecording": "videorecording",
    "webpage": "web site",
}

#: Creator type to its MARC relator code. Anything else contributed.
_ROLES = {
    "editor": "edt",
    "translator": "trl",
    "seriesEditor": "pbd",
    "composer": "cmp",
    "wordsBy": "lyr",
    "performer": "prf",
    "recipient": "rcp",
}

#: Item types whose date is the date the work was issued, and those whose date
#: is taken for a copyright date. Everything else was merely created then.
_ISSUED = frozenset({"journalArticle", "magazineArticle", "newspaperArticle"})
_COPYRIGHTED = frozenset({"book", "bookSection"})

#: A page range written as two numbers and nothing else.
_RANGE = re.compile(r"^\s*([0-9]+) ?[-–] ?([0-9]+)\s*$")  # noqa: RUF001


def _title(value: str, *attributes: tuple[str, str]) -> Element:
    inside = Builder()
    inside.add("title", value)
    return inside.build("titleInfo", *attributes)


def _creator_name(creator_type: str, item_type: str) -> str:
    """Return the MARC relator code for a creator's role."""
    if creator_type == "author":
        # The author of a letter wrote it rather than authored it.
        return "cre" if item_type == "letter" else "aut"
    return _ROLES.get(creator_type, "ctb")


def _record(item: ExportItem) -> Element:
    partial = item.item_type in _PARTIAL
    mods = Builder()
    host = Builder()
    series = Builder()
    # For something published inside something else, most of what describes the
    # publication belongs to the host rather than to the piece.
    outer = host if partial else mods

    if item.get("title"):
        mods.add_element(_title(item.get("title")))
    if item.get("shortTitle"):
        mods.add_element(_title(item.get("shortTitle"), ("type", "abbreviated")))

    mods.add("typeOfResource", _RESOURCE_TYPES.get(item.item_type, ""))
    mods.add("genre", item.item_type, ("authority", "local"))
    outer.add("genre", _MARC_GENRES.get(item.item_type, ""), ("authority", "marcgt"))
    mods.add("genre", item.get("thesisType") or item.get("type"))

    for creator in item.creators:
        name = Builder()
        if creator.single:
            name.add("namePart", creator.last_name)
        else:
            name.add("namePart", creator.last_name, ("type", "family"))
            name.add("namePart", creator.first_name, ("type", "given"))
        role = Builder()
        role.add(
            "roleTerm",
            _creator_name(creator.creator_type, item.item_type),
            ("type", "code"),
            ("authority", "marcrelator"),
        )
        name.add_element(role.build("role"))

        element = name.build("name", ("type", "corporate" if creator.single else "personal"))
        if creator.creator_type == "seriesEditor":
            series.add_element(element)
        elif creator.creator_type == "editor":
            outer.add_element(element)
        else:
            mods.add_element(element)

    record_info = Builder()
    record_info.add("recordContentSource", item.get("libraryCatalog"))
    mods.add("accessCondition", item.get("rights"))

    part = Builder()
    for detail in ("volume", "issue", "section"):
        if value := item.get(detail):
            number = Builder()
            number.add("number", value)
            part.add_element(number.build("detail", ("type", detail)))

    if pages := item.get("pages"):
        extent = Builder()
        if match := _RANGE.match(pages):
            extent.add("start", match.group(1))
            extent.add("end", match.group(2))
        else:
            extent.add("list", pages)
        part.add_element(extent.build("extent", ("unit", "pages")))
    if part.children:
        outer.add_element(part.build("part"))

    origin = Builder()
    origin.add("edition", item.get("edition"))
    if place := item.get("place"):
        location = Builder()
        location.add("placeTerm", place, ("type", "text"))
        origin.add_element(location.build("place"))
    origin.add("publisher", item.get("publisher"))
    if date := item.get("date"):
        if item.item_type in _COPYRIGHTED:
            kind = "copyrightDate"
        elif item.item_type in _ISSUED:
            kind = "dateIssued"
        else:
            kind = "dateCreated"
        origin.add(kind, date)

    if numbered := item.get("numPages"):
        description = Builder()
        description.add("extent", f"{numbered} p.")
        mods.add_element(description.build("physicalDescription"))

    # A journal or a magazine keeps coming; everything else was published once.
    if partial and item.item_type in _ISSUED:
        origin.add("issuance", "continuing")
    elif (
        partial
        and item.item_type
        in {
            "bookSection",
            "conferencePaper",
            "dictionaryEntry",
            "encyclopediaArticle",
        }
    ) or not partial:
        origin.add("issuance", "monographic")
    if origin.children:
        outer.add_element(origin.build("originInfo"))

    outer.add("identifier", item.get("ISBN"), ("type", "isbn"))
    outer.add("identifier", item.get("ISSN"), ("type", "issn"))
    mods.add("identifier", item.get("DOI"), ("type", "doi"))

    if container := item.get("publicationTitle"):
        host.add_element(_title(container))
    if abbreviation := item.get("journalAbbreviation"):
        host.add_element(_title(abbreviation, ("type", "abbreviated")))

    outer.add("classification", item.get("callNumber"))

    if url := item.get("url"):
        location = Builder()
        attributes = [("usage", "primary display")]
        if access := item.get("accessDate"):
            attributes.append(("dateLastAccessed", access))
        location.add("url", url, *attributes)
        mods.add_element(location.build("location"))

    if archived := item.get("archiveLocation"):
        location = Builder()
        location.add("physicalLocation", archived)
        outer.add_element(location.build("location"))

    mods.add("abstract", item.get("abstractNote"))

    series_title = Builder()
    series_title.add("title", item.get("series"))
    series_title.add("title", item.get("seriesTitle"))
    series_title.add("subTitle", item.get("seriesText"))
    if series_title.children:
        series.add_element(series_title.build("titleInfo"))
    if number := item.get("seriesNumber"):
        detail = Builder()
        detail.add("number", number)
        series_part = Builder()
        series_part.add_element(detail.build("detail", ("type", "volume")))
        series.add_element(series_part.build("part"))

    for tag in item.tag_names:
        subject = Builder()
        subject.add("topic", tag)
        mods.add_element(subject.build("subject"))

    if language := item.get("language"):
        element = Builder()
        element.add("languageTerm", language, ("type", "text"))
        mods.add_element(element.build("language"))

    mods.add("note", item.get("extra"))

    if record_info.children:
        mods.add_element(record_info.build("recordInfo"))
    if host.children:
        mods.add_element(host.build("relatedItem", ("type", "host")))
    if series.children:
        # Inside the host for a partial item, which is where the series of the
        # journal or the book belongs.
        outer.add_element(series.build("relatedItem", ("type", "series")))
    return mods.build("mods")


class Mods(TextWriter):
    """A `<modsCollection>`."""

    def __init__(self) -> None:
        self.written = 0

    def begin(self) -> str:
        return '<?xml version="1.0"?>\n'

    def entries(self, items: Sequence[ExportItem]) -> str:
        if not items:
            return ""
        opening = "" if self.written else _COLLECTION_START
        self.written += len(items)
        return opening + "".join(_record(item).compact() for item in items)

    def end(self) -> str:
        return "</modsCollection>" if self.written else _EMPTY_COLLECTION


_COLLECTION_ATTRIBUTES = (
    f'xmlns="{MODS_NAMESPACE}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    f'xsi:schemaLocation="{MODS_NAMESPACE} '
    f'http://www.loc.gov/standards/mods/v3/mods-3-2.xsd"'
)
_COLLECTION_START = f"<modsCollection {_COLLECTION_ATTRIBUTES}>"
#: A collection holding nothing closes itself, as a DOM serialiser writes it.
_EMPTY_COLLECTION = f"<modsCollection {_COLLECTION_ATTRIBUTES}/>"
