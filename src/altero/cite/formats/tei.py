"""TEI, the text-encoding initiative's `<biblStruct>`.

A port of `TEI.js`. The shape of an entry turns on one question: whether the
item is part of something larger. An article, a chapter and an entry are
*analytic* -- their own title sits in `<analytic>` and their container's in
`<monogr>` -- and a book, a report and a thesis are not, so their title is the
`<monogr>`'s own. Everything else follows from that, including which creators
go where: an analytic item's authors belong to the article and its editors to
the book.

Every entry carries an `xml:id` somebody can cite it by, built from the first
creator and the year, or taken from `Citation Key:` in the item's `Extra` field
where there is one -- which is how a library kept with Better BibTeX keeps its
keys. Where upstream differs is what it does about two items that produce the
same id: it renames the earlier entry and numbers from `b`. A file written in
batches cannot go back and rename an entry that has already been sent, so the
first keeps the plain id here and the second is the one that gains a letter.
"""

import re
from collections.abc import Sequence

from altero.cite.dates import date_parts
from altero.cite.exportitem import Creator, ExportItem
from altero.cite.formats import TextWriter
from altero.cite.formats.xmlwriter import Builder, Element

TEI_NAMESPACE = "http://www.tei-c.org/ns/1.0"

#: Item types whose own title is not the title of the thing that was published:
#: they sit inside something else, which `<monogr>` describes.
_ANALYTIC = frozenset(
    {
        "journalArticle",
        "bookSection",
        "magazineArticle",
        "newspaperArticle",
        "conferencePaper",
        "encyclopediaArticle",
        "dictionaryEntry",
        "webpage",
    }
)

#: The fields a container title may be stored under, in the order the
#: translator tries them.
_CONTAINERS = (
    "bookTitle",
    "proceedingsTitle",
    "encyclopediaTitle",
    "dictionaryTitle",
    "publicationTitle",
    "websiteTitle",
)

#: Creator types that are an element of their own rather than a statement of
#: responsibility.
_NAMED_ROLES = {
    "author": "author",
    "editor": "editor",
    "seriesEditor": "editor",
    "bookAuthor": "author",
}

#: A citation key recorded in `Extra`, which is where Better BibTeX keeps one.
_CITATION_KEY = re.compile(r"(?:^|\n)citation key\s*:\s*(\S+)(?:\n|$)", re.IGNORECASE)

#: What separates the words of an id: spaces, brackets, colons, and the
#: punctuation and dashes between `!` and `,` and between the two quotation
#: dashes. Written as escapes because that is how the translator writes it.
_ID_SEPARATORS = re.compile("[ \t\\[\\]:\u00ad\u0021-\u002c\u2010-\u2021]+")

#: What an XML name may hold, and what it may begin with. Everything outside
#: the first is dropped and a leading character outside the second goes with it.
_NAME_CHARACTERS = (
    "A-Z_a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf\ufdf0-\ufffd"
)
_ID_FORBIDDEN = re.compile(f"[^\\-{_NAME_CHARACTERS}.0-9\u00b7\u0300-\u036f\u203f-\u2040]")
_ID_FORBIDDEN_START = re.compile(f"^[^{_NAME_CHARACTERS}]")

#: Zotero's own inline markup, in TEI's words. The result is written as text
#: rather than as markup, exactly as upstream writes it: the translator builds
#: the string and then hands it to a text node.
_FORMATTING = (
    ("<i>", '<hi rend="italics">'),
    ("</i>", "</hi>"),
    ("<b>", '<hi rend="bold">'),
    ("</b>", "</hi>"),
    ("<sub>", '<hi rend="sub">'),
    ("</sub>", "</hi>"),
    ("<sup>", '<hi rend="sup">'),
    ("</sup>", "</hi>"),
)


def _formatted(value: str) -> str:
    for zotero, tei in _FORMATTING:
        value = value.replace(zotero, tei)
    return value


def _creator(creator: Creator) -> Element:
    """Return one creator, as the element its role calls for."""
    inside = Builder()
    if creator.single:
        inside.add("name", creator.last_name)
    else:
        inside.add("forename", creator.first_name)
        # A surname is a `<surname>` beside a forename and a bare `<name>`
        # without one, there being nothing to tell it apart from.
        inside.add("surname" if creator.first_name else "name", creator.last_name)

    role = _NAMED_ROLES.get(creator.creator_type)
    if role:
        return inside.build(role)

    # Anything else is a statement of responsibility naming what the person did.
    statement = Builder()
    statement.add("resp", creator.creator_type)
    statement.add_element(inside.build("persName"))
    return statement.build("respStmt")


def citation_id(item: ExportItem) -> str:
    """Return the `xml:id` an entry is cited by."""
    if match := _CITATION_KEY.search(item.get("extra")):
        return match.group(1)
    # The schema has had a `citationKey` field of its own since 2021; before
    # that, Better BibTeX kept one in `Extra`, and both are still in use.
    if key := item.get("citationKey"):
        return key

    first = item.creators[0] if item.creators else None
    if first is None or not first.last_name:
        # Nothing to build a name from, so the item's own key it is.
        return f"zoteroItem_{item.key}"

    name = first.last_name
    if parts := date_parts(item.get("date")):
        name += str(parts[0])
    name = _ID_SEPARATORS.sub("_", name)
    return _ID_FORBIDDEN.sub("", _ID_FORBIDDEN_START.sub("", name))


def _series(item: ExportItem) -> Element | None:
    if not item.get("series", "seriesTitle"):
        return None
    inside = Builder()
    inside.add("title", _formatted(item.get("series")), ("level", "s"))
    inside.add(
        "title", _formatted(item.get("seriesTitle")), ("level", "s"), ("type", "alternative")
    )
    inside.add("note", item.get("seriesText"), ("type", "description"))
    inside.add("biblScope", item.get("seriesNumber"), ("unit", "volume"))
    return inside.build("series")


def _imprint(item: ExportItem) -> Element:
    inside = Builder()
    inside.add("pubPlace", item.get("place"))
    inside.add("biblScope", item.get("volume"), ("unit", "volume"))
    inside.add("biblScope", item.get("issue"), ("unit", "issue"))
    inside.add("biblScope", item.get("section"), ("unit", "chapter"))
    inside.add("biblScope", item.get("pages"), ("unit", "page"))
    inside.add("publisher", item.get("publisher"))

    date = item.get("date")
    if date:
        parts = date_parts(date)
        inside.add("date", str(parts[0]) if parts else date)
    else:
        # An imprint must hold something, so an item with no date carries an
        # empty one rather than nothing at all.
        inside.add_element(Element("date"))

    inside.add("note", item.get("accessDate"), ("type", "accessed"))
    inside.add("note", item.get("url"), ("type", "url"))
    inside.add("note", item.get("thesisType"), ("type", "thesisType"))
    return inside.build("imprint")


def _entry(item: ExportItem, identifier: str) -> Element:
    analytic = Builder()
    monogr = Builder()
    is_analytic = item.item_type in _ANALYTIC

    if is_analytic:
        analytic.add_element(
            Element("title", (("level", "a"),), text=_formatted(item.get("title")))
        )
        # A DOI on something published inside something else belongs to the
        # part, not to the whole.
        analytic.add("idno", item.get("DOI"), ("type", "DOI"))
        container = item.get(*_CONTAINERS)
        level = "j" if item.item_type == "journalArticle" else "m"
        monogr.add("title", _formatted(container), ("level", level))
        analytic.add("title", item.get("shortTitle"), ("type", "short"))
    else:
        title = _formatted(item.get("title"))
        if title:
            monogr.add("title", title, ("level", "m"))
        elif not item.get("conferenceName"):
            monogr.add_element(Element("title"))
        monogr.add("title", item.get("shortTitle"), ("type", "short"))
        monogr.add("idno", item.get("DOI"), ("type", "DOI"))

    monogr.add("title", _formatted(item.get("conferenceName")), ("type", "conferenceName"))

    series = _series(item)
    series_inside = Builder(list(series.children)) if series else None

    monogr.add("idno", item.get("ISBN"), ("type", "ISBN"))
    monogr.add("idno", item.get("ISSN"), ("type", "ISSN"))
    monogr.add("idno", item.get("callNumber"), ("type", "callNumber"))
    monogr.add("extent", item.get("numberOfVolumes"))

    for creator in item.creators:
        element = _creator(creator)
        if creator.creator_type == "seriesEditor" and series_inside is not None:
            series_inside.add_element(element)
        elif is_analytic and creator.creator_type not in {"editor", "bookAuthor"}:
            analytic.add_element(element)
        else:
            monogr.add_element(element)

    monogr.add("edition", item.get("edition", "version"))
    monogr.add_element(_imprint(item))

    entry = Builder()
    if is_analytic:
        entry.add_element(analytic.build("analytic"))
    entry.add_element(monogr.build("monogr"))
    if series_inside is not None:
        entry.add_element(series_inside.build("series"))

    return entry.build(
        "biblStruct",
        ("type", item.item_type),
        ("xml:id", identifier),
        ("corresp", item.uri),
    )


class Tei(TextWriter):
    """A `<listBibl>` of `<biblStruct>` entries."""

    #: An attachment and a standalone note are both skipped by name upstream.
    #: Tags are left out as well: the translator has an "Export Tags" option and
    #: it is off unless somebody turns it on, which nothing here can.
    skips = frozenset({"note", "attachment", "annotation"})

    def __init__(self) -> None:
        self.taken: set[str] = set()
        self.written = 0

    def begin(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?>\n'

    def entries(self, items: Sequence[ExportItem]) -> str:
        if not items:
            return ""
        opening = "" if self.written else f'<listBibl xmlns="{TEI_NAMESPACE}">'
        self.written += len(items)
        # The one translator Zotero hands the item to without its compatibility
        # mappings; see `ExportItem.plain`.
        return opening + "".join(
            _entry(view, self._identifier(view)).compact()
            for view in (item.plain() for item in items)
        )

    def _identifier(self, item: ExportItem) -> str:
        stem = citation_id(item)
        candidate, suffix = stem, ord("a")
        while candidate in self.taken:
            candidate = f"{stem}{chr(suffix)}"
            suffix = suffix + 1 if suffix < ord("z") else ord("a")
            stem = stem if suffix != ord("a") else f"{stem}a"
        self.taken.add(candidate)
        return candidate

    def end(self) -> str:
        if self.written:
            return "</listBibl>"
        # An empty list closes itself, which is what a DOM serialiser writes.
        return f'<listBibl xmlns="{TEI_NAMESPACE}"/>'
