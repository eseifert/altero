"""EndNote XML, which EndNote and a good many other managers read.

A port of `Endnote XML.js`. A record is a fixed run of elements in a fixed
order -- :data:`_RECORD` -- and most of them are one field looked up per item
type in :data:`_FIELDS`, the same tag-to-field-per-type table `RefWorks Tagged`
has and with mostly the same entries. Six of them are containers with rules of
their own: the titles, the contributors, the dates, the periodical, the
keywords and the URLs.

The document carries no indentation, because upstream serialises a DOM straight
out; and every newline in it is written as `&#xD;`, which is EndNote's own
convention for a line break inside a field and is applied to the whole document
at the end. Both are reproduced: a reader of this format is a program, and an
abstract that gains a newline has been changed.
"""

import re
from collections.abc import Sequence

from altero.cite.dates import date_parts
from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter
from altero.cite.formats.xmlwriter import Builder, Element

#: The elements of a record, in the order they are written. The ones with no
#: field and no rule are still listed, because the order is the format.
_RECORD = (
    "database", "source-app", "rec-number", "ref-type", "contributors",
    "auth-address", "auth-affiliaton", "titles", "periodical", "pages", "volume",
    "number", "issue", "secondary-volume", "secondary-issue", "num-vols", "edition",
    "section", "reprint-edition", "reprint-status", "keywords", "dates", "pub-location",
    "publisher", "orig-pub", "isbn", "accession-num", "call-num", "report-id", "coden",
    "electronic-resource-num", "abstract", "label", "image", "caption", "notes",
    "research-notes", "work-type", "reviewed-item", "availability", "remote-source",
    "meeting-place", "work-location", "work-extent", "pack-method", "size", "repro-ratio",
    "remote-database-name", "remote-database-provider", "language", "urls", "access-date",
    "modified-date", "custom1", "custom2", "custom3", "custom4", "custom5", "custom6",
    "custom7", "misc1", "misc2", "misc3",
)  # fmt: skip

#: The titles a record may carry, inside `<titles>`.
_TITLES = (
    "title",
    "secondary-title",
    "tertiary-title",
    "alt-title",
    "short-title",
    "translated-title",
)

#: The creator groups, inside `<contributors>`. Each holds `<author>` elements
#: whatever the group is called.
_CONTRIBUTORS = (
    "authors",
    "secondary-authors",
    "tertiary-authors",
    "subsidiary-authors",
    "translated-authors",
)

#: Item type to what EndNote calls it, and to its reference number. The two
#: tables disagree in places -- a `videoRecording` is "Audiovisual Material"
#: numbered 3, a `case` is "Case" numbered 6, which is also a book -- and both
#: are copied as they are, because the number is what EndNote reads.
_TYPE_NAMES = {
    "artwork": "Artwork",
    "audioRecording": "Music",
    "bill": "Bill",
    "blogPost": "Blog",
    "book": "Book",
    "bookSection": "Book Section",
    "case": "Case",
    "computerProgram": "Computer Program",
    "conferencePaper": "Conference Proceedings",
    "dictionaryEntry": "Dictionary",
    "document": "Generic",
    "mail": "Personal Communication",
    "encyclopediaArticle": "Encyclopedia",
    "film": "Film or Broadcast",
    "forumPost": "Web Page",
    "hearing": "Hearing",
    "instantMessage": "Personal Communication",
    "interview": "Personal Communication",
    "journalArticle": "Journal Article",
    "letter": "Personal Communication",
    "magazineArticle": "Magazine Article",
    "manuscript": "Manuscript",
    "map": "Map",
    "newspaperArticle": "Newspaper Article",
    "patent": "Patent",
    "podcast": "Film or Broadcast",
    "presentation": "Conference Paper",
    "radioBroadcast": "Film or Broadcast",
    "report": "Report",
    "statute": "Statute",
    "thesis": "Thesis",
    "tvBroadcast": "Film or Broadcast",
    "videoRecording": "Audiovisual Material",
    "webpage": "Web Page",
}

_TYPE_NUMBERS = {
    "artwork": "2",
    "videoRecording": "3",
    "bill": "4",
    "blogPost": "56",
    "book": "6",
    "bookSection": "5",
    "case": "6",
    "computerProgram": "9",
    "presentation": "47",
    "conferencePaper": "10",
    "dictionaryEntry": "52",
    "encyclopediaArticle": "53",
    "film": "21",
    "podcast": "21",
    "radioBroadcast": "21",
    "tvBroadcast": "21",
    "document": "13",
    "hearing": "14",
    "journalArticle": "17",
    "magazineArticle": "19",
    "manuscript": "36",
    "map": "20",
    "audioRecording": "61",
    "newspaperArticle": "23",
    "patent": "25",
    "email": "26",
    "instantMessage": "26",
    "interview": "26",
    "letter": "26",
    "report": "27",
    "statute": "31",
    "thesis": "32",
    "forumPost": "12",
    "webpage": "12",
}

#: Element to the field it is written from. A plain string is the same field for
#: every item type; a mapping names the types each candidate applies to, with
#: `__default` for the rest and `__exclude` for the types that get nothing.
_FIELDS: dict[str, str | dict[str, list[str]]] = {
    "abstract": "abstractNote",
    "call-num": "callNumber",
    "electronic-resource-num": "DOI",
    "remote-database-name": "libraryCatalog",
    "abbr-1": "journalAbbreviation",
    "short-title": "shortTitle",
    "full-title": "publicationTitle",
    "language": "language",
    "access-date": "accessDate",
    "title": {
        "__default": ["title"],
        "subject": ["email"],
        "caseName": ["case"],
        "nameOfAct": ["statute"],
    },
    "secondary-title": {
        "code": ["bill", "statute"],
        "bookTitle": ["bookSection"],
        "blogTitle": ["blogPost"],
        "conferenceName": ["conferencePaper"],
        "dictionaryTitle": ["dictionaryEntry"],
        "encyclopediaTitle": ["encyclopediaArticle"],
        "committee": ["hearing"],
        "forumTitle": ["forumPost"],
        "websiteTitle": ["webpage"],
        "programTitle": ["radioBroadcast", "tvBroadcast"],
        "meetingName": ["presentation"],
        "seriesTitle": ["computerProgram", "map", "report"],
        "series": ["book"],
        "reporter": ["case"],
        "publicationTitle": ["journalArticle", "magazineArticle", "newspaperArticle"],
    },
    "tertiary-title": {
        "legislativeBody": ["hearing", "bill"],
        "series": ["bookSection", "conferencePaper"],
        "seriesTitle": ["audioRecording"],
    },
    "authors": {
        "__default": ["author"],
        "artist": ["artwork"],
        "cartographer": ["map"],
        "composer": ["audioRecording"],
        "director": ["film", "radioBroadcast", "tvBroadcast", "videoRecording"],
        "interviewee": ["interview"],
        "inventor": ["patent"],
        "podcaster": ["podcast"],
        "programmer": ["computerProgram"],
    },
    "secondary-authors": {
        "sponsor": ["bill"],
        "performer": ["audioRecording"],
        "presenter": ["presentation"],
        "interviewer": ["interview"],
        "editor": [
            "journalArticle",
            "bookSection",
            "conferencePaper",
            "dictionaryEntry",
            "document",
            "encyclopediaArticle",
        ],
        "seriesEditor": ["book", "report"],
        "recipient": ["email", "instantMessage", "letter"],
        "issuingAuthority": ["patent"],
    },
    "tertiary-authors": {
        "cosponsor": ["bill"],
        "producer": ["film", "tvBroadcast", "videoRecording", "radioBroadcast"],
        "editor": ["book"],
        "seriesEditor": [
            "bookSection",
            "conferencePaper",
            "dictionaryEntry",
            "encyclopediaArticle",
            "map",
        ],
    },
    "subsidiary-authors": {
        "__default": ["translator"],
        "counsel": ["case"],
        "castMember": ["radioBroadcast", "tvBroadcast", "videoRecording"],
        "contributor": ["conferencePaper", "film"],
    },
    "work-type": {
        "manuscriptType": ["manuscript"],
        "websiteType": ["webpage"],
        "genre": ["film"],
        "postType": ["forumPost"],
        "letterType": ["letter"],
        "mapType": ["map"],
        "presentationType": ["presentation"],
        "reportType": ["report"],
        "thesisType": ["thesis"],
    },
    "custom1": {
        "filingDate": ["patent"],
        "scale": ["map"],
        "place": ["conferencePaper"],
    },
    "custom2": {"issueDate": ["patent"]},
    "custom3": {
        "artworkSize": ["artwork"],
        "proceedingsTitle": ["conferencePaper"],
        "runningTime": ["videoRecording"],
        "country": ["patent"],
    },
    "custom4": {"creators/attorneyAgent": ["patent"], "genre": ["film"]},
    "custom5": {
        "references": ["patent"],
        "audioRecordingFormat": ["audioRecording", "radioBroadcast"],
        "videoRecordingFormat": ["film", "tvBroadcast", "videoRecording"],
    },
    "custom6": {"legalStatus": ["patent"]},
    "pub-location": {"__default": ["place"], "__exclude": ["conferencePaper"]},
    "pub-dates": {
        "__default": ["date"],
        "dateEnacted": ["statute"],
        "dateDecided": ["case"],
        "issueDate": ["patent"],
    },
    "edition": {
        "__default": ["edition"],
        "session": ["bill", "hearing", "statute"],
        "version": ["computerProgram"],
    },
    "issue": {"__default": ["issue"], "numberOfVolumes": ["bookSection"]},
    "misc1": {
        "seriesNumber": ["book"],
        "billNumber": ["bill"],
        "system": ["computerProgram"],
        "documentNumber": ["hearing"],
        "applicationNumber": ["patent"],
        "publicLawNumber": ["statute"],
        "episodeNumber": ["podcast", "radioBroadcast", "tvBroadcast"],
    },
    "misc2": {
        "manuscriptType": ["manuscript"],
        "mapType": ["map"],
        "reportType": ["report"],
        "thesisType": ["thesis"],
        "websiteType": ["blogPost", "webpage"],
        "postType": ["forumPost"],
        "letterType": ["letter"],
        "interviewMedium": ["interview"],
        "presentationType": ["presentation"],
        "artworkMedium": ["artwork"],
        "audioFileType": ["podcast"],
    },
    "num-vols": {"__default": ["numberOfVolumes"], "__exclude": ["bookSection"]},
    "orig-pub": {
        "history": ["hearing", "statute", "bill", "case"],
        "priorityNumbers": ["patent"],
    },
    "publisher": {
        "__default": ["publisher"],
        "label": ["audioRecording"],
        "court": ["case"],
        "distributor": ["film"],
        "assignee": ["patent"],
        "institution": ["report"],
        "university": ["thesis"],
        "company": ["computerProgram"],
        "studio": ["videoRecording"],
        "network": ["radioBroadcast", "tvBroadcast"],
    },
    "year": {
        "__default": ["date"],
        "dateEnacted": ["statute"],
        "dateDecided": ["case"],
        "issueDate": ["patent"],
    },
    "section": {"__default": ["section"], "__exclude": ["case"]},
    "isbn": {
        "__default": ["ISBN"],
        "ISSN": ["journalArticle", "magazineArticle", "newspaperArticle"],
        "patentNumber": ["patent"],
        "reportNumber": ["report"],
    },
    "pages": {
        "__default": ["pages"],
        "codePages": ["bill"],
        "numPages": ["book", "thesis", "manuscript"],
        "firstPage": ["case"],
        "runningTime": ["film"],
    },
    "number": {
        "seriesNumber": ["bookSection", "book"],
        "issue": ["journalArticle", "magazineArticle"],
        "docketNumber": ["case"],
        "artworkSize": ["artwork"],
    },
    "volume": {
        "__default": ["volume"],
        "codeNumber": ["statute"],
        "codeVolume": ["bill"],
        "reporterVolume": ["case"],
        "__exclude": ["patent", "webpage"],
    },
}

#: EndNote's own way of writing a line break inside a field.
_NEWLINES = re.compile(r"\r\n?|\n")


def field_for(item_type: str, element: str) -> str | None:
    """Return the field one element is written from, for one item type."""
    entry = _FIELDS.get(element)
    if entry is None:
        return None
    if isinstance(entry, str):
        return entry

    default: str | None = None
    excluded = False
    found: str | None = None
    for field, types in entry.items():
        if field == "__default":
            default = types[0]
        elif field == "__exclude":
            excluded = excluded or item_type in types
        elif item_type in types:
            found = field
    if found:
        return found
    return None if excluded else default


def _titles(item: ExportItem) -> Element:
    inside = Builder()
    for name in _TITLES:
        field = field_for(item.item_type, name)
        inside.add(name, item.get(field) if field else "")
    return inside.build("titles")


def _contributors(item: ExportItem) -> Element | None:
    """Return the creators, grouped as EndNote groups them.

    A patent's attorney or agent is not a contributor here but a field --
    `custom4` -- which is why this returns it separately.
    """
    if not item.creators:
        return None
    inside = Builder()
    for group in _CONTRIBUTORS:
        role = field_for(item.item_type, group)
        if role is None:
            continue
        names = Builder()
        for creator in item.creators_of(role):
            names.add("author", creator.name)
        if names.children:
            inside.add_element(names.build(group))
    return inside.build("contributors")


def _dates(item: ExportItem) -> Element:
    inside = Builder()
    field = field_for(item.item_type, "pub-dates")
    value = item.get(field) if field else ""
    if value:
        if parts := date_parts(value):
            inside.add("year", str(parts[0]))
        dates = Builder()
        dates.add("date", value)
        inside.add_element(dates.build("pub-dates"))
    return inside.build("dates")


def _periodical(item: ExportItem) -> Element | None:
    inside = Builder()
    for name in ("full-title", "abbr-1"):
        field = field_for(item.item_type, name)
        inside.add(name, item.get(field) if field else "")
    return inside.build("periodical") if inside.children else None


def _urls(item: ExportItem) -> Element | None:
    if not item.get("url"):
        return None
    web = Builder()
    web.add("url", item.get("url"))
    inside = Builder()
    inside.add_element(web.build("web-urls"))
    return inside.build("urls")


def _record(item: ExportItem) -> Element:
    record = Builder()
    for name in _RECORD:
        if name == "database":
            record.add("database", "MyLibrary", ("name", "MyLibrary"))
        elif name == "source-app":
            # Named as the application that wrote the file, which is this one.
            record.add("source-app", "altero", ("name", "altero"))
        elif name == "ref-type":
            record.add(
                "ref-type",
                _TYPE_NUMBERS.get(item.item_type, ""),
                ("name", _TYPE_NAMES.get(item.item_type, "")),
            )
        elif name == "titles":
            record.add_element(_titles(item))
        elif name == "contributors":
            attorneys = item.creators_of("attorneyAgent")
            if attorneys:
                record.add("custom4", "; ".join(creator.name for creator in attorneys))
            record.add_element(_contributors(item))
        elif name == "dates":
            record.add_element(_dates(item))
        elif name == "periodical":
            record.add_element(_periodical(item))
        elif name == "keywords":
            if item.tags:
                keywords = Builder()
                for tag in item.tag_names:
                    keywords.add("keyword", tag)
                record.add_element(keywords.build("keywords"))
        elif name == "urls":
            record.add_element(_urls(item))
        elif name == "research-notes":
            # Only child notes go here, and an export sends each item on its own.
            continue
        else:
            field = field_for(item.item_type, name)
            record.add(name, item.get(field) if field else "")
    return record.build("record")


class EndNoteXml(TextWriter):
    """EndNote XML.

    `<records>` opens on the first record rather than with the document, so a
    file holding none is `<records/>` -- which is what a DOM serialiser writes
    for an element with no children and so what upstream produces.
    """

    def __init__(self) -> None:
        self.written = 0

    def begin(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?>\n<xml>'

    def entries(self, items: Sequence[ExportItem]) -> str:
        if not items:
            return ""
        opening = "" if self.written else "<records>"
        self.written += len(items)
        return opening + _NEWLINES.sub("&#xD;", "".join(_record(item).compact() for item in items))

    def end(self) -> str:
        return "</records></xml>" if self.written else "<records/></xml>"
