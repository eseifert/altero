"""RefWorks Tagged, the tagged format RefWorks reads.

A port of `RefWorks Tagged.js`. Its field table is the largest of any of the
export translators, because RefWorks has one set of tags for everything and
Zotero has a different field for the same idea on each item type: `T2` is the
journal of an article, the book a section is in, the committee a hearing sat
before and the code a statute belongs to.

The table is kept in the translator's own shape -- tag, then field, then the
item types that field applies to -- so it can be read against the original line
by line. Anything with a `__default` uses it for every type not named, unless
that type is in `__exclude`.

Two quirks are preserved. `SP` splits a page range and writes the second half
as `OP`, and an item whose pages are a single number gets neither, because the
translator only fills the value in when the range matches. And the default
order contains `"OP,"` -- a comma inside the string -- so `OP` is never reached
from the order itself; it is written by `SP` or not at all.
"""

import re
from collections.abc import Sequence

from altero.cite.dates import date_parts
from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter

#: Item type to RefWorks reference type. Anything absent is `Generic`.
_TYPES = {
    "artwork": "Artwork",
    "audioRecording": "Sound Recording",
    "bill": "Bills",
    "blogPost": "Web Page",
    "book": "Book, Whole",
    "bookSection": "Book, Section",
    "case": "Case",
    "computerProgram": "Computer Program",
    "conferencePaper": "Conference Proceedings",
    "email": "Personal Communication",
    "film": "Motion Picture",
    "forumPost": "Online Discussion Forum",
    "hearing": "Hearing",
    "journalArticle": "Journal Article",
    "letter": "Personal Communication",
    "magazineArticle": "Magazine Article",
    "manuscript": "Unpublished Material",
    "map": "Map",
    "newspaperArticle": "Newspaper Article",
    "patent": "Patent",
    "report": "Report",
    "statute": "Statutes",
    "thesis": "Dissertation",
    "videoRecording": "Video",
    "webpage": "Web Page",
}

DEFAULT_TYPE = "Generic"

#: Tag to what it holds: a field name, or the item types each candidate field
#: applies to. `creators/<type>` is every creator of that type.
_FIELDS: dict[str, str | dict[str, list[str]]] = {
    "AB": "abstractNote",
    "CN": "callNumber",
    "DO": "DOI",
    "SL": "archive",
    "LL": "archiveLocation",
    "IS": "issue",
    "JO": "journalAbbreviation",
    "K1": "tags",
    "LK": "attachments/other",
    "NO": "notes",
    "ST": "shortTitle",
    "RD": "accessDate",
    "UL": "url",
    "T1": {
        "__default": ["title"],
        "subject": ["email"],
        "caseName": ["case"],
        "nameOfAct": ["statute"],
    },
    "T2": {
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
        "publicationTitle": ["journalArticle", "magazineArticle", "newspaperArticle"],
    },
    "T3": {
        "legislativeBody": ["hearing", "bill"],
        "series": ["bookSection", "conferencePaper"],
        "seriesTitle": ["audioRecording"],
    },
    "A1": {
        "__default": ["creators/author"],
        "creators/artist": ["artwork"],
        "creators/cartographer": ["map"],
        "creators/composer": ["audioRecording"],
        "creators/director": ["film", "radioBroadcast", "tvBroadcast", "videoRecording"],
        "creators/interviewee": ["interview"],
        "creators/inventor": ["patent"],
        "creators/podcaster": ["podcast"],
        "creators/programmer": ["computerProgram"],
    },
    "A2": {
        "creators/sponsor": ["bill"],
        "creators/performer": ["audioRecording"],
        "creators/presenter": ["presentation"],
        "creators/interviewer": ["interview"],
        "creators/editor": [
            "journalArticle",
            "bookSection",
            "conferencePaper",
            "dictionaryEntry",
            "document",
            "encyclopediaArticle",
        ],
        "creators/seriesEditor": ["book"],
        "creators/recipient": ["email", "instantMessage", "letter"],
        "reporter": ["case"],
        "issuingAuthority": ["patent"],
    },
    "A3": {
        "creators/cosponsor": ["bill"],
        "creators/producer": ["film", "tvBroadcast", "videoRecording", "radioBroadcast"],
        "creators/editor": ["book"],
        "creators/seriesEditor": [
            "bookSection",
            "conferencePaper",
            "dictionaryEntry",
            "encyclopediaArticle",
            "map",
            "report",
        ],
    },
    "A4": {
        "__default": ["creators/translator"],
        "creators/counsel": ["case"],
        "creators/contributor": ["conferencePaper", "film"],
    },
    "U1": {
        "filingDate": ["patent"],
        "creators/castMember": ["radioBroadcast", "tvBroadcast", "videoRecording"],
        "scale": ["map"],
        "place": ["conferencePaper"],
    },
    "U2": {
        "issueDate": ["patent"],
        "creators/bookAuthor": ["bookSection"],
        "creators/commenter": ["blogPost"],
    },
    "U3": {
        "artworkSize": ["artwork"],
        "proceedingsTitle": ["conferencePaper"],
        "country": ["patent"],
    },
    "U4": {
        "creators/wordsBy": ["audioRecording"],
        "creators/attorneyAgent": ["patent"],
        "genre": ["film"],
    },
    "U5": {
        "references": ["patent"],
        "audioRecordingFormat": ["audioRecording", "radioBroadcast"],
        "videoRecordingFormat": ["film", "tvBroadcast", "videoRecording"],
    },
    "U6": {"legalStatus": ["patent"]},
    # A conference paper's place is `U1` instead, so it is excluded here rather
    # than written twice.
    "PP": {"__default": ["place"], "__exclude": ["conferencePaper"]},
    "FD": {
        "__default": ["date"],
        "dateEnacted": ["statute"],
        "dateDecided": ["case"],
        "issueDate": ["patent"],
    },
    "ED": {
        "__default": ["edition"],
        "session": ["bill", "hearing", "statute"],
        "version": ["computerProgram"],
    },
    "LA": {"__default": ["language"], "programmingLanguage": ["computerProgram"]},
    "CL": {
        "billNumber": ["bill"],
        "system": ["computerProgram"],
        "documentNumber": ["hearing"],
        "applicationNumber": ["patent"],
        "publicLawNumber": ["statute"],
        "episodeNumber": ["podcast", "radioBroadcast", "tvBroadcast"],
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
    "PB": {
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
    # The same field as `FD`, written as the year alone.
    "YR": {
        "__default": ["date"],
        "dateEnacted": ["statute"],
        "dateDecided": ["case"],
        "issueDate": ["patent"],
    },
    "SN": {
        "__default": ["ISBN"],
        "ISSN": ["journalArticle", "magazineArticle", "newspaperArticle"],
        "patentNumber": ["patent"],
        "reportNumber": ["report"],
    },
    "SP": {
        "__default": ["pages"],
        "codePages": ["bill"],
        "numPages": ["book", "thesis", "manuscript"],
        "firstPage": ["case"],
        "runningTime": ["film"],
    },
    "VO": {
        "__default": ["volume"],
        "codeNumber": ["statute"],
        "codeVolume": ["bill"],
        "reporterVolume": ["case"],
        "__exclude": ["patent"],
    },
}

#: The order the tags are written in. `"OP,"` is the translator's own typo and
#: is left as it is: it matches no field, so nothing is written for it, and
#: correcting it would emit a tag upstream never does.
_ORDER = (
    "T1", "A1", "T2", "A2", "T3", "A3", "A4", "AB", "U1", "U2", "U3", "U4", "U5", "U6",
    "CN", "PP", "FD", "YR", "DO", "SL", "LL", "ED", "VO", "IS", "SP", "OP,", "JO", "LA",
    "CL", "PB", "SN", "ST", "UL", "RD", "LK", "NO", "K1",
)  # fmt: skip

#: A bill's sponsor and cosponsor belong together, so the body they sat in does
#: not come between them.
_BILL_ORDER = (
    "T1", "A1", "T2", "A2", "A3", "T3", "A4", "AB", "U1", "U2", "U3", "U4", "U5", "U6",
    "CN", "PP", "FD", "YR", "DO", "SL", "LL", "ED", "VO", "IS", "SP", "OP", "JO", "LA",
    "CL", "PB", "SN", "ST", "UL", "RD", "LK", "NO", "K1",
)  # fmt: skip

_BREAK = "\r\n"

#: What separates the two halves of a page range: any of the dashes somebody
#: might have typed, or whitespace.
_RANGE = re.compile("(.+?)[\u002d\u00ad\u2010-\u2015\u2212\u2e3a\u2e3b\\s]+(.+)")


def field_for(item_type: str, tag: str) -> str | None:
    """Return the field one tag is written from, for one item type."""
    entry = _FIELDS.get(tag)
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


def _access_date(value: str) -> str:
    """Return an access date as `YYYY/MM/DD/part`, which is RefWorks's shape.

    The `part` is whatever the parser could not read as a date, which for a
    stored timestamp is the time of day. Every slash is written whether or not
    what goes between them is known.
    """
    parts = date_parts(value)
    if not parts:
        return value
    year = f"{parts[0]:04d}"
    month = f"{parts[1]:02d}" if len(parts) > 1 else ""
    day = f"{parts[2]:02d}" if len(parts) > 2 else ""
    return f"{year}/{month}/{day}/{value.partition(' ')[2].strip()}"


class RefWorks(TextWriter):
    """RefWorks Tagged."""

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "".join(self._entry(item) for item in items)

    def _entry(self, item: ExportItem) -> str:
        lines = [_tag("RT", [_TYPES.get(item.item_type, DEFAULT_TYPE)])]
        order = _BILL_ORDER if item.item_type == "bill" else _ORDER

        for tag in order:
            field = field_for(item.item_type, tag)
            if field is None:
                continue
            lines.append(self._value(item, tag, field))
        # An entry is followed by a blank line, and the last line of it ended
        # in a break of its own.
        return "".join(lines) + _BREAK * 2

    def _value(self, item: ExportItem, tag: str, field: str) -> str:
        kind, _, qualifier = field.partition("/")

        if kind == "creators":
            return _tag(tag, [creator.name for creator in item.creators_of(qualifier)])
        if kind == "tags":
            return _tag(tag, item.tag_names)
        # Neither notes nor attachments come along: an export sends each item on
        # its own, so there are no children to name.
        if kind in {"notes", "attachments"}:
            return ""
        if kind == "pages" and tag == "SP":
            match = _RANGE.match(item.get("pages").strip())
            # No range, no `SP`: the translator leaves the value unset, and a
            # tag with no value is not written.
            return "" if not match else _tag("SP", [match.group(1)]) + _tag("OP", [match.group(2)])
        if tag == "YR":
            parts = date_parts(item.get(field))
            return _tag(tag, [f"{parts[0]:04d}" if parts else item.get(field)])
        if tag == "RD":
            return _tag(tag, [_access_date(item.get(field))])
        return _tag(tag, [item.get(field)])


def _tag(tag: str, values: Sequence[str]) -> str:
    """Return one tagged line per value, skipping the empty ones."""
    return "".join(f"{tag} {value.strip()}{_BREAK}" for value in values if value and value.strip())
