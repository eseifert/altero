"""The spreadsheet: one row per item, one column per field Zotero has.

A port of `CSV.js`. Its column list is fixed and in a deliberate order --
what somebody reads first, then the common fields, then every creator type,
then the fields only a few item types have -- so it is copied here as it is
written there rather than derived from the schema, which would reorder it at
every schema update and break every spreadsheet built on the old one.

Three of its quirks are worth naming. The file opens with a byte order mark,
because the spreadsheet everybody opens it in assumes the local code page
without one. A row is *preceded* by its newline rather than followed by it, so
the file ends without one. And the two date columns disagree with each other:
`Date Added` is written the way the client stores it and `Date Modified` the
way the API answers with it -- upstream converts only the first and a reader
parsing both has always had to handle it.

The `Notes`, `File Attachments` and `Link Attachments` columns are written and
always empty, as they are upstream: an export sends each item on its own, so
nothing here has children to name.
"""

import csv
import io
import re
from collections.abc import Iterable, Sequence

from altero.cite.dates import date_parts, iso_date
from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter

#: The columns, in the order they are written. A name with a slash is not a
#: field: `creators/editor` is every editor, `tags/own` the tags somebody typed,
#: `attachments/path` the files.
COLUMNS = (
    "key",
    "itemType",
    "publicationYear",
    "creators/author",
    "title",
    "publicationTitle",
    "ISBN",
    "ISSN",
    "DOI",
    "url",
    "abstractNote",
    "date",
    "dateAdded",
    "dateModified",
    "accessDate",
    "pages",
    "numPages",
    "issue",
    "volume",
    "numberOfVolumes",
    "journalAbbreviation",
    "shortTitle",
    "series",
    "seriesNumber",
    "seriesText",
    "seriesTitle",
    "publisher",
    "place",
    "language",
    "rights",
    "type",
    "archive",
    "archiveLocation",
    "libraryCatalog",
    "callNumber",
    "extra",
    "notes",
    "attachments/path",
    "attachments/url",
    "tags/own",
    "tags/automatic",
    "creators/editor",
    "creators/seriesEditor",
    "creators/translator",
    "creators/contributor",
    "creators/attorneyAgent",
    "creators/bookAuthor",
    "creators/castMember",
    "creators/commenter",
    "creators/composer",
    "creators/cosponsor",
    "creators/counsel",
    "creators/interviewer",
    "creators/producer",
    "creators/recipient",
    "creators/reviewedAuthor",
    "creators/scriptwriter",
    "creators/wordsBy",
    "creators/guest",
    "number",
    "edition",
    "runningTime",
    "scale",
    "medium",
    "artworkSize",
    "filingDate",
    "applicationNumber",
    "assignee",
    "issuingAuthority",
    "country",
    "meetingName",
    "conferenceName",
    "court",
    "references",
    "reporter",
    "legalStatus",
    "priorityNumbers",
    "programmingLanguage",
    "version",
    "system",
    "code",
    "codeNumber",
    "section",
    "session",
    "committee",
    "history",
    "legislativeBody",
)

#: Creator types that stand in for `author` on the type that has them, so that
#: a film's director and an interview's interviewee land in the Author column
#: rather than in none at all.
_BASE_CREATOR_TYPES = {
    "interviewee": "author",
    "director": "author",
    "artist": "author",
    "sponsor": "author",
    "contributor": "author",
    "inventor": "author",
    "cartographer": "author",
    "performer": "author",
    "presenter": "author",
    "podcaster": "author",
    "programmer": "author",
}

#: What separates several values in one cell.
_SEPARATOR = "; "

_CAMEL = re.compile(r"([a-z])([A-Z])")

#: A cell holds one line: a spreadsheet reading a quoted newline is not wrong,
#: but every one of them has a different idea of what to do with it.
_NEWLINES = re.compile(r"[\r\n]+")


def heading(column: str) -> str:
    """Return the heading of one column.

    The label is the field name with its words split apart and its first letter
    raised: `abstractNote` becomes `Abstract Note`, and `ISBN`, having no such
    boundary, is left as it is.
    """
    kind, _, qualifier = column.partition("/")
    if kind == "creators":
        label = qualifier
    elif kind == "tags":
        label = "Automatic Tags" if qualifier == "automatic" else "Manual Tags"
    elif kind == "attachments":
        label = "Link Attachments" if qualifier == "url" else "File Attachments"
    else:
        label = kind
    return _CAMEL.sub(r"\1 \2", label[:1].upper() + label[1:])


def _value(item: ExportItem, column: str) -> str:
    kind, _, qualifier = column.partition("/")

    if kind == "key":
        return item.key
    if kind == "itemType":
        return item.item_type
    if kind == "publicationYear":
        parts = date_parts(item.get("date"))
        return str(parts[0]) if parts else ""
    if kind == "creators":
        return _SEPARATOR.join(
            creator.name
            for creator in item.creators
            if qualifier in {creator.creator_type, _BASE_CREATOR_TYPES.get(creator.creator_type)}
        )
    if kind == "tags":
        wanted = 1 if qualifier == "automatic" else 0
        return _SEPARATOR.join(name for name, type_ in item.tags if type_ == wanted)
    if kind in {"attachments", "notes"}:
        return ""
    if kind == "date":
        raw = item.get("date")
        return iso_date(raw) or raw
    if kind == "dateAdded":
        return item.date_added
    if kind == "dateModified":
        return item.date_modified
    return item.get(kind)


class Csv(TextWriter):
    """One row per item."""

    def begin(self) -> str:
        return "﻿" + _row(heading(column) for column in COLUMNS)

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "".join("\n" + _row(_value(item, column) for column in COLUMNS) for item in items)


def _row(values: Iterable[str]) -> str:
    """Return one row, every cell quoted and its newlines flattened to spaces."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="")
    writer.writerow([_NEWLINES.sub(" ", value) for value in values])
    return buffer.getvalue()
