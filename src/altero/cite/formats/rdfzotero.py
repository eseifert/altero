"""Zotero RDF, the format Zotero's own "Export Library" writes.

A port of `Zotero RDF.js`. Unlike every other format here it does not ask for
fields by name: it walks the item's fields in order and decides what each one
means as it goes -- which is why :attr:`ExportItem.unique` exists and why a
field nothing knows about still comes out, as `z:<name>`, rather than being
dropped.

An entry is not one resource but several. The work itself is one; the journal
or book it appeared in is another, and it is the container that carries the
volume, the issue and the ISSN, because those describe the journal rather than
the article. The publisher is a third, with the place of publication inside it
as an address. A container with an ISSN is addressed by it -- `urn:issn:...` --
and so is written as a resource of its own that the entry points at; everything
else is a blank node written where it is mentioned.

What identifies the entry itself, in order: its ISBN, its URL, or a node id.
Two entries never share one, so the second book with the same ISBN gets the id.
"""

from collections.abc import Sequence
from urllib.parse import quote

from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter
from altero.cite.formats.rdfwriter import DOCUMENT_END, Node, document_start

#: What `encodeURI` leaves alone, which is what the identifiers are built with:
#: it escapes the characters that cannot appear in a URI and no others, so a
#: comma inside an ISSN stays a comma.
_URI_SAFE = "-_.!~*'();/?:@&=+$,#"

#: Every namespace the format uses, in the order upstream declares them.
NAMESPACES = (
    ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("z", "http://www.zotero.org/namespaces/export#"),
    ("dc", "http://purl.org/dc/elements/1.1/"),
    ("dcterms", "http://purl.org/dc/terms/"),
    ("bib", "http://purl.org/net/biblio#"),
    ("foaf", "http://xmlns.com/foaf/0.1/"),
    ("vcard", "http://nwalsh.com/rdf/vCard#"),
    ("prism", "http://prismstandard.org/namespaces/1.2/basic/"),
    ("link", "http://purl.org/rss/1.0/modules/link/"),
)

#: What an item is, and what it is part of. A type of `None` means the entry is
#: an `rdf:Description` -- an encyclopedia article is described only by the book
#: it is in.
_TYPES: dict[str, tuple[str | None, str | None]] = {
    "book": ("bib:Book", None),
    "bookSection": ("bib:BookSection", "bib:Book"),
    "journalArticle": ("bib:Article", "bib:Journal"),
    "magazineArticle": ("bib:Article", "bib:Periodical"),
    "newspaperArticle": ("bib:Article", "bib:Newspaper"),
    "thesis": ("bib:Thesis", None),
    "letter": ("bib:Letter", None),
    "manuscript": ("bib:Manuscript", None),
    "interview": ("bib:Interview", None),
    "film": ("bib:MotionPicture", None),
    "artwork": ("bib:Illustration", None),
    "webpage": ("bib:Document", "z:Website"),
    "note": ("bib:Memo", None),
    "attachment": ("z:Attachment", None),
    "report": ("bib:Report", None),
    "bill": ("bib:Legislation", None),
    "case": ("bib:Document", "bib:CourtReporter"),
    "hearing": ("bib:Report", None),
    "patent": ("bib:Patent", None),
    "statute": ("bib:Legislation", None),
    "email": ("bib:Letter", None),
    "map": ("bib:Image", None),
    "blogPost": ("bib:Document", "z:Blog"),
    "instantMessage": ("bib:Letter", None),
    "forumPost": ("bib:Document", "z:Forum"),
    "audioRecording": ("bib:Recording", None),
    "presentation": ("bib:ConferenceProceedings", None),
    "videoRecording": ("bib:Recording", None),
    "tvBroadcast": ("bib:Recording", None),
    "radioBroadcast": ("bib:Recording", None),
    "podcast": ("bib:Recording", None),
    "computerProgram": ("bib:Data", None),
    "encyclopediaArticle": (None, "bib:Book"),
    "dictionaryEntry": (None, "bib:Book"),
    "conferencePaper": (None, "bib:Journal"),
}

#: Creator types biblio has a word for. The rest go in Zotero's own namespace.
_BIBLIO_CREATORS = frozenset({"author", "editor", "contributor"})

#: Fields naming what kind of thing an item is, which all become `dc:type`.
_TYPE_FIELDS = frozenset(
    {
        "reportType",
        "videoRecordingType",
        "letterType",
        "manuscriptType",
        "mapType",
        "thesisType",
        "websiteType",
        "audioRecordingType",
        "presentationType",
        "postType",
        "audioFileType",
    }
)

#: Fields that say nothing about the work: they are the library's bookkeeping.
_IGNORED = frozenset(
    {"itemID", "itemType", "firstCreator", "dateAdded", "dateModified", "section", "sourceItemID"}
)

#: The fields that describe the container rather than the work, and what each
#: is called there.
_CONTAINER_FIELDS = {
    "publicationTitle": "dc:title",
    "reporter": "dc:title",
    "journalAbbreviation": "dcterms:alternative",
    "volume": "prism:volume",
    "issue": "prism:number",
    "number": "prism:number",
    "patentNumber": "prism:number",
}

#: The fields that describe the series.
_SERIES_FIELDS = {
    "series": "dc:title",
    "seriesTitle": "dcterms:alternative",
    "seriesText": "dc:description",
    "seriesNumber": "dc:identifier",
}

#: The fields that name the organisation behind the work.
_PUBLISHER_FIELDS = frozenset({"publisher", "distributor", "label", "company", "institution"})

#: Fields with a word of their own, and the predicate each is written under.
_SIMPLE_FIELDS = {
    "title": "dc:title",
    "source": "dc:source",
    "accessionNumber": "dc:identifier",
    "rights": "dc:rights",
    "edition": "prism:edition",
    "version": "prism:edition",
    "date": "dc:date",
    "accessDate": "dcterms:dateSubmitted",
    "issueDate": "dcterms:issued",
    "pages": "bib:pages",
    "extra": "dc:description",
    "mimeType": "link:type",
    "charset": "link:charset",
    "abstractNote": "dcterms:abstract",
    "archiveLocation": "dc:coverage",
    "interviewMedium": "dcterms:medium",
    "artworkMedium": "dcterms:medium",
}


def _wrapped(type_name: str, predicate: str, value: str) -> Node:
    """Return a node of one type carrying one value, for the identifiers that
    are a resource rather than a string."""
    node = Node(type_name)
    node.add(predicate, value)
    return node


class ZoteroRdf(TextWriter):
    """Zotero RDF."""

    #: Every item is described, an attachment and a note included: this is the
    #: format Zotero's own library export is written in.
    skips = frozenset({"annotation"})

    def __init__(self) -> None:
        self.written = 0
        #: Addresses already spoken for, so two items cannot claim one.
        self.taken: set[str] = set()

    def begin(self) -> str:
        return document_start(NAMESPACES)

    def entries(self, items: Sequence[ExportItem]) -> str:
        rendered = []
        for item in items:
            self.written += 1
            entry, containers = self._entry(item, self.written)
            named = [node.about for node in containers if node.about]
            rendered.append(entry.render(named=named))
            rendered += [node.render() for node in containers]
        return "".join(rendered)

    def end(self) -> str:
        return DOCUMENT_END

    def _address(self, item: ExportItem, number: int) -> str:
        """Return what identifies this item: its ISBN, its URL, or a node id."""
        isbn = item.get("ISBN")
        if isbn and (candidate := f"urn:isbn:{quote(isbn, safe=_URI_SAFE)}") not in self.taken:
            self.taken.add(candidate)
            return candidate
        url = item.get("url")
        if item.item_type != "attachment" and url and url not in self.taken:
            self.taken.add(url)
            return url
        return f"#item_{number}"

    def _entry(self, item: ExportItem, number: int) -> tuple[Node, list[Node]]:
        type_name, container_type = _TYPES.get(item.item_type, (None, None))
        entry = Node(type_name, self._address(item, number))
        entry.add("z:itemType", item.item_type)

        section = None
        if item.get("section"):
            section = _wrapped("bib:Part", "dc:title", item.get("section"))
            entry.add_node("dcterms:isPartOf", section)

        container = None
        if container_type:
            issn = item.get("ISSN")
            address = f"urn:issn:{quote(issn, safe=_URI_SAFE)}" if issn else None
            if address and address in self.taken:
                address = None
            if address:
                self.taken.add(address)
            container = Node(container_type, address)
            (section or entry).add_node("dcterms:isPartOf", container)

        series = None
        if item.get("series", "seriesTitle", "seriesText", "seriesNumber"):
            series = Node("bib:Series")
            (container or entry).add_node("dcterms:isPartOf", series)

        organization = None
        if item.get(*_PUBLISHER_FIELDS, "place"):
            organization = Node("foaf:Organization")
            entry.add_node("dc:publisher", organization)

        self._add_creators(item, entry)
        # Before the fields, which is the order the statements come out in.
        self._add_tags(item, entry)
        self._add_fields(item, entry, container, series, organization)
        return entry, [container] if container and container.about else []

    def _add_creators(self, item: ExportItem, entry: Node) -> None:
        """Add the creators, one sequence per role."""
        sequences: dict[str, Node] = {}
        for creator in item.creators:
            person = Node("foaf:Person")
            person.add("foaf:surname", creator.last_name)
            person.add("foaf:givenName", creator.first_name)

            namespace = "bib" if creator.creator_type in _BIBLIO_CREATORS else "z"
            predicate = f"{namespace}:{creator.creator_type}s"
            if predicate not in sequences:
                sequences[predicate] = Node("rdf:Seq")
                entry.add_node(predicate, sequences[predicate])
            sequences[predicate].add_node("rdf:li", person)

    def _add_fields(
        self,
        item: ExportItem,
        entry: Node,
        container: Node | None,
        series: Node | None,
        organization: Node | None,
    ) -> None:
        """Walk the item's fields in order, deciding what each one means."""
        for name, value in item.unique.items():
            if not value or name in _IGNORED:
                continue
            held = container or entry

            if name in _SIMPLE_FIELDS:
                entry.add(_SIMPLE_FIELDS[name], value)
            elif name == "url":
                entry.add_node("dc:identifier", _wrapped("dcterms:URI", "rdf:value", value))
            elif name in {"ISSN", "ISBN", "DOI"}:
                held.add("dc:identifier", f"{name} {value}")
            elif name in _CONTAINER_FIELDS:
                held.add(_CONTAINER_FIELDS[name], value)
            elif name == "callNumber":
                entry.add_node("dc:subject", _wrapped("dcterms:LCC", "rdf:value", value))
            elif name in _SERIES_FIELDS and series is not None:
                series.add(_SERIES_FIELDS[name], value)
            elif name in _PUBLISHER_FIELDS and organization is not None:
                organization.add("foaf:name", value)
            elif name == "place" and organization is not None:
                organization.add_node(
                    "vcard:adr", _wrapped("vcard:Address", "vcard:locality", value)
                )
            elif name == "conferenceName":
                entry.add_node("bib:presentedAt", _wrapped("bib:Conference", "dc:title", value))
            elif name in _TYPE_FIELDS:
                entry.add("dc:type", value)
            elif name == "note":
                # An attachment's note describes the file; a note item's *is*
                # the item.
                entry.add(
                    "dc:description" if item.item_type == "attachment" else "rdf:value", value
                )
            else:
                # Anything else keeps its own name, in Zotero's namespace. That
                # is what makes the format lossless enough to read back in.
                entry.add(f"z:{name}", value)

    def _add_tags(self, item: ExportItem, entry: Node) -> None:
        """Add the tags. One somebody typed is a subject; one that came with the
        item is a resource saying as much."""
        for name, type_ in item.tags:
            if type_ == 1:
                automatic = Node("z:AutomaticTag")
                automatic.add("rdf:value", name)
                entry.add_node("dc:subject", automatic)
            else:
                entry.add("dc:subject", name)
