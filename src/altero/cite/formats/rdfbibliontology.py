"""Bibliontology RDF, which describes a work in BIBO rather than in Zotero's
own vocabulary.

A port of `Bibliontology RDF.js`, and the most structured of the three RDF
formats. It says two things about every item and keeps them apart: what the
work *is*, described in BIBO, and what this library knows about *its copy* of
it -- when it was consulted, where it came from, what it was tagged. The second
is the `z:UserItem`, which points at the first with `res:resource`.

The work itself is up to three resources deep, because BIBO models a journal
article as an article in an issue in a journal. Which of them a field belongs to
is what :data:`_FIELDS` records: a volume describes the issue, an ISSN the
journal, a page range the article. An item type with no issue and no journal --
a book -- collapses all three onto one resource, which is why a book's ISBN and
its title end up side by side.

The work is addressed by its URL, failing that by `info:doi/`, failing that by
`urn:isbn:`, and failing all three it is a blank node. A creator is a blank node
too, and is written once and pointed at, because it is named twice: once as the
creator and once in the author list that records the order.

One difference from upstream: an ISBN field holding two numbers separated by
two spaces produces two statements here and three there, the third of them
empty. It is what splitting on a single space does to a double one, and an
empty `bibo:isbn13` says nothing a reader can use.
"""

from collections.abc import Sequence
from urllib.parse import quote

from altero.cite.exportitem import Creator, ExportItem
from altero.cite.formats import TextWriter
from altero.cite.formats.rdfwriter import DOCUMENT_END, Node, document_start, label_shared_nodes
from altero.itemschema import get_schema

#: Every namespace the format uses.
NAMESPACES = (
    ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("res", "http://purl.org/vocab/resourcelist/schema#"),
    ("z", "http://www.zotero.org/namespaces/export#"),
    ("dcterms", "http://purl.org/dc/terms/"),
    ("bibo", "http://purl.org/ontology/bibo/"),
    ("foaf", "http://xmlns.com/foaf/0.1/"),
    ("address", "http://schemas.talis.com/2005/address/schema#"),
    ("po", "http://purl.org/ontology/po/"),
    ("doap", "http://usefulinc.com/ns/doap#"),
    ("sc", "http://umbel.org/umbel/sc/"),
    ("sioct", "http://rdfs.org/sioc/types#"),
    ("rel", "http://purl.org/vocab/relationship/"),
    ("ctag", "http://commontag.org/ns#"),
)

#: The four resources an entry may be spread across. `ITEM` is the work,
#: `SUBCONTAINER` the issue it appeared in, `CONTAINER` the journal or book that
#: issue belongs to, and `USERITEM` this library's copy of it.
USERITEM, ITEM, SUBCONTAINER, CONTAINER = "useritem", "item", "subcontainer", "container"
ITEM_SERIES, CONTAINER_SERIES = "itemSeries", "containerSeries"

#: What each item type is, and what it is part of: the types of the work, of the
#: subcontainer, and of the container. `None` means the item type has no such
#: resource and whatever would have gone on it goes on the one below.
_TYPES: dict[str, tuple[tuple[str, ...], tuple[str, ...] | None, tuple[str, ...] | None]] = {
    "artwork": (("bibo:Image",), None, None),
    "attachment": (("z:Attachment",), None, None),
    "audioRecording": (("bibo:AudioDocument",), None, None),
    "bill": (("bibo:Bill",), None, ("bibo:Code",)),
    "blogPost": (("sioct:BlogPost", "bibo:Article"), None, ("sioct:Weblog", "bibo:Website")),
    "book": (("bibo:Book",), None, None),
    "bookSection": (("bibo:BookSection",), None, ("bibo:EditedBook",)),
    "case": (("bibo:LegalCaseDocument",), None, ("bibo:CourtReporter",)),
    "computerProgram": (("sc:ComputerProgram_CW", "bibo:Document"), None, None),
    "conferencePaper": (("bibo:Article",), None, ("bibo:Proceedings",)),
    "dictionaryEntry": (("bibo:Article",), None, ("sc:Dictionary", "bibo:ReferenceSource")),
    "document": (("bibo:Document",), None, None),
    "email": (("bibo:Email",), None, None),
    "encyclopediaArticle": (
        ("bibo:Article",),
        None,
        ("sc:Encyclopedia", "bibo:ReferenceSource"),
    ),
    "forumPost": (
        ("sioct:BoardPost", "bibo:Article"),
        None,
        ("sioct:MessageBoard", "bibo:Website"),
    ),
    "film": (("bibo:Film",), None, None),
    "hearing": (("bibo:Hearing",), None, None),
    "instantMessage": (("sioct:InstantMessage", "bibo:PersonalCommunication"), None, None),
    "interview": (("bibo:Interview",), None, None),
    "journalArticle": (("bibo:AcademicArticle",), ("bibo:Issue",), ("bibo:Journal",)),
    "letter": (("bibo:Letter",), None, None),
    "magazineArticle": (("bibo:Article",), ("bibo:Issue",), ("bibo:Magazine",)),
    "manuscript": (("bibo:Manuscript",), None, None),
    "map": (("bibo:Map",), None, None),
    "newspaperArticle": (("bibo:Article",), ("bibo:Issue",), ("bibo:Newspaper",)),
    "note": (("bibo:Note",), None, None),
    "patent": (("bibo:Patent",), None, None),
    "podcast": (("z:Podcast", "bibo:AudioDocument"), None, None),
    "presentation": (("bibo:Slideshow",), None, None),
    "radioBroadcast": (("po:AudioDocument", "po:Episode"), None, ("po:Programme",)),
    "report": (("bibo:Report",), None, None),
    "statute": (("bibo:Statute",), None, ("bibo:Code",)),
    "thesis": (("bibo:Thesis",), None, None),
    "tvBroadcast": (("bibo:AudioVisualDocument", "po:Episode"), None, ("po:Programme",)),
    "videoRecording": (("bibo:AudioVisualDocument",), None, None),
    "webpage": (("bibo:Webpage",), None, ("bibo:Website",)),
}

#: Item types whose subcontainer or container is written even when nothing was
#: said about it, because the item type means it exists.
_ALWAYS = frozenset(
    {
        "conferencePaper",
        "dictionaryEntry",
        "encyclopediaArticle",
        "journalArticle",
        "magazineArticle",
        "newspaperArticle",
    }
)

#: Field to the resource it describes and the predicate it is written under. A
#: tuple of three is a predicate reached through a resource of its own: the
#: publisher's name hangs off a `foaf:Organization`, not off the book.
_FIELDS: dict[str, tuple[str, str | tuple[str, tuple[str, ...], str]]] = {
    "url": (ITEM, "bibo:uri"),
    "rights": (USERITEM, "dcterms:rights"),
    "series": (CONTAINER_SERIES, "dcterms:title"),
    "volume": (SUBCONTAINER, "bibo:volume"),
    "issue": (SUBCONTAINER, "bibo:issue"),
    "edition": (SUBCONTAINER, "bibo:edition"),
    "place": (CONTAINER, ("dcterms:publisher", ("foaf:Organization",), "address:localityName")),
    "country": (CONTAINER, ("dcterms:publisher", ("foaf:Organization",), "address:countryName")),
    "publisher": (CONTAINER, ("dcterms:publisher", ("foaf:Organization",), "foaf:name")),
    "pages": (ITEM, "bibo:pages"),
    "firstPage": (ITEM, "bibo:pageStart"),
    "publicationTitle": (CONTAINER, "dcterms:title"),
    "ISSN": (CONTAINER, "bibo:issn"),
    "date": (SUBCONTAINER, "dcterms:date"),
    "section": (ITEM, "bibo:section"),
    "callNumber": (SUBCONTAINER, "bibo:lccn"),
    "archiveLocation": (ITEM, "dcterms:source"),
    "distributor": (SUBCONTAINER, "bibo:distributor"),
    "extra": (ITEM, "z:extra"),
    "journalAbbreviation": (CONTAINER, "bibo:shortTitle"),
    "DOI": (ITEM, "bibo:doi"),
    "accessDate": (USERITEM, "z:accessDate"),
    "seriesTitle": (ITEM_SERIES, "dcterms:title"),
    "seriesText": (ITEM_SERIES, "dcterms:description"),
    "seriesNumber": (CONTAINER_SERIES, "bibo:number"),
    "code": (CONTAINER, "dcterms:title"),
    "session": (ITEM, ("bibo:presentedAt", ("bibo:Conference",), "dcterms:title")),
    "legislativeBody": (
        ITEM,
        (
            "bibo:organizer",
            ("sc:LegalGovernmentOrganization", "foaf:Organization"),
            "foaf:name",
        ),
    ),
    "history": (ITEM, "z:history"),
    "reporter": (CONTAINER, "dcterms:title"),
    "court": (CONTAINER, "bibo:court"),
    "numberOfVolumes": (CONTAINER_SERIES, "bibo:numberOfVolumes"),
    "committee": (
        ITEM,
        ("bibo:organizer", ("sc:Committee_Organization", "foaf:Organization"), "foaf:name"),
    ),
    "assignee": (ITEM, "z:assignee"),
    "references": (ITEM, "z:references"),
    "legalStatus": (ITEM, "bibo:status"),
    "codeNumber": (CONTAINER, "bibo:number"),
    "number": (ITEM, "bibo:number"),
    "artworkSize": (ITEM, "dcterms:extent"),
    "libraryCatalog": (USERITEM, "z:repository"),
    "archive": (ITEM, "z:repository"),
    "scale": (ITEM, "z:scale"),
    "meetingName": (ITEM, ("bibo:presentedAt", ("bibo:Conference",), "dcterms:title")),
    "runningTime": (ITEM, "po:duration"),
    "version": (ITEM, "doap:revision"),
    "system": (ITEM, "doap:os"),
    "conferenceName": (ITEM, ("bibo:presentedAt", ("bibo:Conference",), "dcterms:title")),
    "language": (ITEM, "dcterms:language"),
    "programmingLanguage": (ITEM, "doap:programming-language"),
    "abstractNote": (ITEM, "dcterms:abstract"),
    "type": (ITEM, "dcterms:type"),
    "medium": (ITEM, "dcterms:medium"),
    "title": (ITEM, "dcterms:title"),
    "shortTitle": (ITEM, "bibo:shortTitle"),
    "numPages": (ITEM, "bibo:numPages"),
    "applicationNumber": (ITEM, "z:applicationNumber"),
    "issuingAuthority": (ITEM, ("bibo:issuer", ("foaf:Organization",), "foaf:name")),
    "filingDate": (ITEM, "dcterms:dateSubmitted"),
}

#: The three ordered lists a creator may be recorded in.
_AUTHOR_LIST, _EDITOR_LIST, _CONTRIBUTOR_LIST = (
    "bibo:authorList",
    "bibo:editorList",
    "bibo:contributorList",
)

#: Creator type to the resource it belongs to, the list it is recorded in, and
#: the predicate naming what the person did.
_CREATORS: dict[str, tuple[str, str, str | tuple[str, tuple[str, ...], str]]] = {
    "author": (ITEM, _AUTHOR_LIST, "dcterms:creator"),
    "attorneyAgent": (ITEM, _CONTRIBUTOR_LIST, "z:attorneyAgent"),
    "bookAuthor": (CONTAINER, _AUTHOR_LIST, "dcterms:creator"),
    "castMember": (ITEM, _CONTRIBUTOR_LIST, "rel:ACT"),
    "commenter": (
        ITEM,
        _CONTRIBUTOR_LIST,
        ("sioct:has_reply", ("sioct:Comment",), "dcterms:creator"),
    ),
    "composer": (ITEM, _CONTRIBUTOR_LIST, "rel:CMP"),
    "contributor": (ITEM, _CONTRIBUTOR_LIST, "dcterms:contributor"),
    "cosponsor": (ITEM, _CONTRIBUTOR_LIST, "rel:SPN"),
    "counsel": (ITEM, _CONTRIBUTOR_LIST, "z:counsel"),
    "director": (ITEM, _CONTRIBUTOR_LIST, "bibo:director"),
    "editor": (SUBCONTAINER, _EDITOR_LIST, "bibo:editor"),
    "guest": (ITEM, _CONTRIBUTOR_LIST, "po:participant"),
    "interviewer": (ITEM, _CONTRIBUTOR_LIST, "bibo:interviewer"),
    "interviewee": (ITEM, _CONTRIBUTOR_LIST, "bibo:interviewee"),
    "performer": (ITEM, _CONTRIBUTOR_LIST, "bibo:performer"),
    "producer": (ITEM, _CONTRIBUTOR_LIST, "bibo:producer"),
    "recipient": (ITEM, _CONTRIBUTOR_LIST, "bibo:recipient"),
    "reviewedAuthor": (ITEM, _CONTRIBUTOR_LIST, ("bibo:reviewOf", (), "dcterms:creator")),
    "scriptwriter": (ITEM, _CONTRIBUTOR_LIST, "rel:AUS"),
    "seriesEditor": (CONTAINER_SERIES, _EDITOR_LIST, "bibo:editor"),
    "translator": (SUBCONTAINER, _CONTRIBUTOR_LIST, "bibo:translator"),
    "wordsBy": (ITEM, _CONTRIBUTOR_LIST, "rel:LYR"),
}

#: What `encodeURI` leaves alone.
_URI_SAFE = "-_.!~*'();/?:@&=+$,#"

#: How a DOI may already be written, and how much of it to drop.
_DOI_PREFIXES = ("doi:", "urn:doi:", "info:doi/", "http://dx.doi.org/")


def _split(value: str) -> list[str]:
    """Return a field holding several numbers as the numbers."""
    return [part for part in value.replace(",", " ").split() if part]


class _Entry:
    """The resources one item is described across."""

    def __init__(self, item: ExportItem, taken: set[str]) -> None:
        self.item = item
        item_types, subcontainer, container = _TYPES.get(
            item.item_type, (("bibo:Document",), None, None)
        )
        self.definitions = {SUBCONTAINER: subcontainer, CONTAINER: container}
        self.always = item.item_type in _ALWAYS

        work = Node(item_types[0], self._address(item, taken))
        for extra in item_types[1:]:
            # A type beyond the first is said rather than named, there being one
            # element to name it with.
            work.add("rdf:type", extra)

        self.nodes = {
            USERITEM: Node("z:UserItem", item.uri),
            ITEM: work,
            CONTAINER: Node(container[0]) if container else work,
        }
        self.nodes[SUBCONTAINER] = Node(subcontainer[0]) if subcontainer else self.nodes[CONTAINER]
        self.nodes[ITEM_SERIES] = Node("bibo:Series")
        self.nodes[CONTAINER_SERIES] = Node("bibo:Series") if container else self.nodes[ITEM_SERIES]
        self.nodes[USERITEM].add_node("res:resource", work)
        #: Blank nodes reached through a predicate, kept so a second field
        #: naming the same organisation lands on the same one.
        self.blanks: dict[tuple[int, str], Node] = {}
        self.lists: dict[tuple[int, str], Node] = {}

    def _address(self, item: ExportItem, taken: set[str]) -> str | None:
        """Return what addresses the work: its URL, its DOI, its ISBN, or
        nothing at all, in which case it is a blank node."""
        for candidate in self._candidates(item):
            if candidate not in taken:
                taken.add(candidate)
                return candidate
        return None

    def _candidates(self, item: ExportItem) -> list[str]:
        candidates = []
        if url := item.get("url"):
            candidates.append(quote(url, safe=_URI_SAFE))
        if doi := item.get("DOI"):
            for prefix in _DOI_PREFIXES:
                if doi.startswith(prefix):
                    doi = doi[len(prefix) :]
                    break
            candidates.append(f"info:doi/{quote(doi, safe=_URI_SAFE)}")
        if isbn := item.get("ISBN"):
            candidates.append(f"urn:isbn:{quote(_split(isbn)[0], safe=_URI_SAFE)}")
        return candidates

    def through(
        self, holder: Node, predicate: str, types: Sequence[str], name: str, value: str
    ) -> None:
        """Say something about a resource reached through ``predicate``,
        making that resource the first time it is needed."""
        key = (id(holder), predicate)
        node = self.blanks.get(key)
        if node is None:
            node = Node(types[0] if types else None)
            for extra in types[1:]:
                node.add("rdf:type", extra)
            self.blanks[key] = node
            holder.add_node(predicate, node)
        node.add(name, value)

    def add_creator(self, creator: Creator, primary: str | None) -> None:
        """Add one creator, both under what they did and in the ordered list."""
        role = creator.creator_type
        mapping = _CREATORS.get(role)
        if mapping is None:
            # A primary creator this vocabulary has no word for is still the
            # creator; anything else keeps its Zotero name.
            mapping = _CREATORS["author"] if role == primary else (ITEM, _AUTHOR_LIST, f"z:{role}")
        holder_name, list_name, predicate = mapping
        holder = self.nodes[holder_name]

        person = Node("foaf:Organization" if creator.single else "foaf:Person")
        if creator.single:
            person.add("foaf:name", creator.last_name)
        else:
            person.add("foaf:givenName", creator.first_name)
            person.add("foaf:surname", creator.last_name)

        if isinstance(predicate, str):
            holder.add_node(predicate, person)
        else:
            reached, types, name = predicate
            key = (id(holder), reached)
            node = self.blanks.get(key)
            if node is None:
                node = Node(types[0] if types else None)
                self.blanks[key] = node
                holder.add_node(reached, node)
            node.add_node(name, person)

        # The primary creator is always in the author list, whatever the
        # vocabulary calls their role.
        if list_name == _CONTRIBUTOR_LIST and role == primary:
            list_name = _AUTHOR_LIST
        key = (id(holder), list_name)
        sequence = self.lists.get(key)
        if sequence is None:
            sequence = Node("rdf:Seq")
            self.lists[key] = sequence
            holder.add_node(list_name, sequence)
        sequence.add_node("rdf:li", person)

    def relate(self) -> None:
        """Attach the containers and the series to what they are part of.

        Done once everything has been said, because a container nobody said
        anything about is not written at all -- unless the item type means it
        exists, which is what `always` records.
        """
        for series, holder in ((ITEM_SERIES, ITEM), (CONTAINER_SERIES, CONTAINER)):
            node = self.nodes[series]
            if node.statements and node is not self.nodes[holder]:
                self.nodes[holder].add_node("dcterms:isPartOf", node)

        for name in (SUBCONTAINER, CONTAINER):
            node = self.nodes[name]
            definition = self.definitions[name]
            if definition is None or node is self.nodes[ITEM]:
                continue
            if not self.always and not node.statements:
                continue
            # Attached to the nearest resource above it that is not itself.
            for parent in (SUBCONTAINER, ITEM) if name is CONTAINER else (ITEM,):
                if self.nodes[parent] is not node:
                    self.nodes[parent].add_node("dcterms:isPartOf", node)
                    break

    def roots(self) -> list[Node]:
        return [self.nodes[USERITEM], self.nodes[ITEM]]


class BibliontologyRdf(TextWriter):
    """Bibliontology RDF."""

    #: A standalone note is skipped by name upstream; an attachment has a type
    #: in the table and is described.
    skips = frozenset({"note", "annotation"})

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def begin(self) -> str:
        return document_start(NAMESPACES)

    def end(self) -> str:
        return DOCUMENT_END

    def entries(self, items: Sequence[ExportItem]) -> str:
        rendered = []
        for item in items:
            entry = _Entry(item, self.taken)
            self._add_fields(item, entry)
            self._add_creators(item, entry)
            self._add_tags(item, entry)
            entry.relate()

            roots = entry.roots()
            shared = label_shared_nodes(roots)
            named = [node.about for node in roots if node.about]
            rendered += [node.render(named=named) for node in roots]
            rendered += [node.render() for node in shared]
        return "".join(rendered)

    def _add_fields(self, item: ExportItem, entry: _Entry) -> None:
        for name, value in item.unique.items():
            if not value:
                continue
            if name == "ISBN":
                # An ISBN of ten digits is the old kind and of thirteen the new,
                # and an item may carry both.
                for isbn in _split(value):
                    entry.nodes[CONTAINER].add(
                        "bibo:isbn10" if len(isbn) == 10 else "bibo:isbn13", isbn
                    )
                continue
            if name == "priorityNumbers":
                for number in _split(value):
                    entry.nodes[ITEM].add("z:priorityNumber", number)
                continue

            holder_name, predicate = _FIELDS.get(name, (ITEM, f"z:{name}"))
            holder = entry.nodes[holder_name]
            if isinstance(predicate, str):
                holder.add(predicate, value)
            else:
                reached, types, leaf = predicate
                entry.through(holder, reached, types, leaf, value)

    def _add_creators(self, item: ExportItem, entry: _Entry) -> None:
        schema = get_schema()
        primary = (
            schema.get_item_type(item.item_type).primary_creator_type
            if schema.is_valid_item_type(item.item_type)
            else None
        )
        for creator in item.creators:
            entry.add_creator(creator, primary)

    def _add_tags(self, item: ExportItem, entry: _Entry) -> None:
        """Tags belong to this library's copy rather than to the work: somebody
        here filed it that way."""
        for name, type_ in item.tags:
            tag = Node("ctag:UserTag" if type_ == 0 else "ctag:AutoTag")
            tag.add("ctag:label", name)
            entry.nodes[USERITEM].add_node("ctag:tagged", tag)
