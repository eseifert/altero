"""Wikipedia citation templates: `{{Cite journal| title = ...}}`.

A port of `Wikipedia Citation Templates.js`. The template a citation goes into
decides what its parts are called -- an episode has `credits` and a city where a
book has `others` and a location -- so most of this module is that decision,
made once per item and then written out.

The order the parameters come out in is the order the translator fills its
`properties` object, which is JavaScript's insertion order and is reproduced
here by filling a dict in the same sequence. It is not alphabetical and not the
template's documented order; it is simply what everybody's wiki markup already
looks like.

Two of the translator's quirks are kept because a citation is text somebody
pastes into an article: only the *first* pipe in a value is replaced by
`{{!}}`, and only the first run of non-digits in a page range becomes an en
dash. Both are `String.replace` with a string pattern, which in JavaScript
replaces once.
"""

import re
from collections.abc import Sequence
from typing import Any

from altero.cite.dates import date_parts
from altero.cite.exportitem import Creator, ExportItem
from altero.cite.formats import TextWriter
from altero.itemschema import get_schema

#: Item type to citation template. Anything absent is a bare `{{Cite}}`, which
#: is what a note exports as.
_TEMPLATES = {
    "book": "Cite book",
    "bookSection": "Cite book",
    "journalArticle": "Cite journal",
    "magazineArticle": "Cite news",
    "newspaperArticle": "Cite news",
    "thesis": "Cite paper",
    "letter": "Cite",
    "manuscript": "Cite book",
    "interview": "Cite interview",
    "film": "Cite AV media",
    "artwork": "Cite",
    "webpage": "Cite web",
    "report": "Cite conference",
    "bill": "Cite",
    "hearing": "Cite",
    "patent": "Cite",
    "statute": "Cite",
    "email": "Cite email",
    "map": "Cite",
    "blogPost": "Cite web",
    "instantMessage": "Cite",
    "forumPost": "Cite web",
    "audioRecording": "Cite",
    "presentation": "Cite paper",
    "videoRecording": "Cite AV media",
    "tvBroadcast": "Cite episode",
    "radioBroadcast": "Cite episode",
    "podcast": "Cite podcast",
    "computerProgram": "Cite",
    "conferencePaper": "Cite conference",
    "document": "Cite",
    "encyclopediaArticle": "Cite encyclopedia",
    "dictionaryEntry": "Cite encyclopedia",
}

#: Template parameter to item field, in the order they are written.
_FIELDS = (
    ("edition", "edition"),
    ("publisher", "publisher"),
    ("doi", "DOI"),
    ("isbn", "ISBN"),
    ("issn", "ISSN"),
    ("conference", "conferenceName"),
    ("volume", "volume"),
    ("issue", "issue"),
    ("pages", "pages"),
    ("number", "episodeNumber"),
)

#: An identifier the `Extra` field may be carrying.
_EXTRA_IDENTIFIERS = (
    ("pmid", re.compile(r"^PMID\s*:\s*([0-9]+)", re.MULTILINE)),
    ("pmc", re.compile(r"^PMCID\s*:\s*((?:PMC)?[0-9]+)", re.MULTILINE)),
)

#: An identifier a URL gives away by itself.
_URL_IDENTIFIERS = (
    ("pmid", re.compile(r"www\.ncbi\.nlm\.nih\.gov/pubmed/([0-9]+)", re.IGNORECASE)),
    ("pmc", re.compile(r"www\.ncbi\.nlm\.nih\.gov/pmc/articles/((?:PMC)?[0-9]+)", re.IGNORECASE)),
    ("jstor", re.compile(r"www\.jstor\.org/stable/([^?#]+)", re.IGNORECASE)),
)


def _creator_label(creator_type: str) -> str:
    """Return the English name of a creator type, as the templates spell it."""
    return get_schema().display_names().get("creatorTypes", {}).get(creator_type, creator_type)


def _names(creators: Sequence[Creator], *, with_types: bool = False) -> str:
    """Return creators as `First Last`, the way a sentence would list them."""
    parts = []
    for creator in creators:
        name = creator.display_name
        parts.append(f"{name} ({_creator_label(creator.creator_type)})" if with_types else name)
    return ", ".join(parts)


def _leading_name(creator: Creator, *, with_types: bool = False) -> str:
    """Return the first creator, which is the one written surname first."""
    name = creator.last_name
    if creator.last_name and creator.first_name:
        name += ", "
    name += creator.first_name
    return f"{name} ({_creator_label(creator.creator_type)})" if with_types else name


def _date(value: str) -> str:
    """Return as much of a date as is known, in the shape a template takes.

    The translator builds `yyyy-mm-dd` with `00` standing in for what it does
    not know and then cuts the unknown parts off again, which is how a year on
    its own stays a year.
    """
    parts = date_parts(value)
    if not parts:
        return ""
    return "-".join(f"{part:02d}" if index else f"{part:04d}" for index, part in enumerate(parts))


def _stamp(value: str) -> str:
    """Return the date half of a stored timestamp: `2018-03-14 02:34:19`."""
    return value.partition(" ")[0] if " " in value else ""


class Wikipedia(TextWriter):
    """Wikipedia citation templates."""

    #: A note has no template of its own and comes out as a bare `{{Cite}}`,
    #: which is what upstream writes for one.
    skips = frozenset({"attachment", "annotation"})

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "\r\n".join(self._entry(item) for item in items)

    def _entry(self, item: ExportItem) -> str:
        template = _TEMPLATES.get(item.item_type, "Cite")
        properties: dict[str, Any] = {}

        for parameter, field in _FIELDS:
            if value := item.get(field):
                properties[parameter] = value

        if item.creators:
            self._add_creators(item, template, properties)
        self._add_titles(item, template, properties)

        if template == "Cite web" and (kind := item.get("type")):
            properties["format"] = kind

        if place := item.get("place"):
            properties["city" if template == "Cite episode" else "location"] = place

        if series := item.get("series", "seriesTitle", "seriesText"):
            properties["series"] = series

        # A journal with nothing to open is not something anybody visited on a
        # given day, so it carries no access date.
        access = item.get("accessDate")
        if access and not (item.item_type == "journalArticle" and not item.get("url")):
            properties["access-date"] = _stamp(access)

        if date := item.get("date"):
            if template == "Cite email":
                properties["senddate"] = _stamp(date)
            elif written := _date(date):
                properties["date"] = written

        if running := item.get("runningTime"):
            properties["minutes" if template == "Cite episode" else "time"] = running

        if item.get("url") and access:
            properties["chapterurl" if item.item_type == "bookSection" else "url"] = item.get("url")

        if pages := properties.get("pages"):
            # An en dash between the page numbers, replacing the first run of
            # anything else -- which is the separator when there is one.
            properties["pages"] = re.sub(r"[^0-9]+", "–", str(pages), count=1)  # noqa: RUF001

        self._add_identifiers(item, properties)
        return self._markup(template, properties)

    def _add_creators(self, item: ExportItem, template: str, properties: dict[str, Any]) -> None:
        creators = list(item.creators)

        if template == "Cite episode":
            properties["credits"] = _names(creators, with_types=True)
            return
        if template == "Cite AV media":
            leading = creators.pop(0)
            people = _leading_name(leading, with_types=True)
            if creators:
                people += ", " + _names(creators, with_types=True)
            properties["people"] = people
            if kind := item.get("type"):
                properties["medium"] = kind
            return
        if template == "Cite email":
            authors = [creator for creator in creators if creator.creator_type == "author"]
            if not authors:
                return
            written = _leading_name(authors[0])
            if authors[1:]:
                written += ", " + _names(authors[1:])
            properties["author"] = written
            return
        if template == "Cite interview":
            self._add_interview_creators(item, creators, properties)
            return

        editors = [creator for creator in creators if creator.creator_type == "editor"]
        translators = [creator for creator in creators if creator.creator_type == "translator"]
        rest = [
            creator
            for creator in creators
            if creator.creator_type not in {"editor", "translator", "contributor"}
        ]

        others = ""
        if editors:
            written = _names(editors) + (" (ed.)" if len(editors) == 1 else " (eds.)")
            # The documentation says the editor of a chapter, and only of a
            # chapter, is named as such; everybody else's editor is "others".
            if item.item_type == "bookSection" or template in {
                "Cite conference",
                "Cite encyclopedia",
            }:
                properties["editors"] = written
            else:
                others = written
        if translators:
            others = f"{others}, " if others else others
            others += _names(translators) + " (trans.)"

        if rest:
            properties["authors"] = rest
        if others:
            properties["others"] = others

    def _add_interview_creators(
        self, item: ExportItem, creators: list[Creator], properties: dict[str, Any]
    ) -> None:
        interviewers = [creator for creator in creators if creator.creator_type == "interviewer"]
        translators = [creator for creator in creators if creator.creator_type == "translator"]
        interviewees = [
            creator
            for creator in creators
            if creator.creator_type not in {"interviewer", "translator", "contributor"}
        ]

        if interviewers:
            properties["interviewer"] = _names(interviewers[:1])
            if interviewers[1:]:
                properties["cointerviewers"] = _names(interviewers[1:])
        if translators:
            joined = properties.get("cointerviewers")
            written = f"{joined}, " if joined else ""
            properties["cointerviewers"] = written + _names(translators)

        # Up to four interviewees, each in a numbered pair of parameters.
        for index, interviewee in enumerate(interviewees[:4], start=1):
            suffix = "" if index == 1 else str(index)
            properties[f"last{suffix}"] = interviewee.last_name
            properties[f"first{suffix}"] = interviewee.first_name

        if medium := item.get("medium"):
            properties["type"] = medium

    def _add_titles(self, item: ExportItem, template: str, properties: dict[str, Any]) -> None:
        container = item.get("publicationTitle")
        if item.item_type == "bookSection":
            properties["title"] = container
            properties["chapter"] = item.get("title")
            return

        properties["title"] = item.get("title")
        if template == "Cite journal":
            properties["journal"] = container
        elif template == "Cite conference":
            properties["booktitle"] = container
        elif template == "Cite encyclopedia":
            properties["encyclopedia"] = container
        else:
            properties["work"] = container

    def _add_identifiers(self, item: ExportItem, properties: dict[str, Any]) -> None:
        for name, pattern in _EXTRA_IDENTIFIERS:
            if match := pattern.search(item.get("extra")):
                properties[name] = match.group(1)
        if url := item.get("url"):
            for name, pattern in _URL_IDENTIFIERS:
                if properties.get(name):
                    continue
                if match := pattern.search(url):
                    properties[name] = match.group(1)

    def _markup(self, template: str, properties: dict[str, Any]) -> str:
        parts = [f"{{{{{template}"]
        for key, value in properties.items():
            if not value:
                continue
            if key == "authors":
                creators: Sequence[Creator] = value
                # One author is `last`; several are numbered from one.
                numbered = len(creators) > 1
                for index, creator in enumerate(creators):
                    suffix = str(index + 1) if index or numbered else ""
                    parts.append(f"| last{suffix} = {creator.last_name}")
                    if creator.first_name:
                        parts.append(f"| first{suffix} = {creator.first_name}")
            else:
                parts.append(f"| {key} = {str(value).replace('|', '{{!}}', 1)}")
        return "".join(parts) + "}}"
