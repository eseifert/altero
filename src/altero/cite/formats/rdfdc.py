"""Unqualified Dublin Core, as RDF/XML.

A port of `Unqualified Dublin Core RDF.js`, which is the smallest of the three
RDF formats and the least opinionated: fifteen elements, all of them literals,
and the subject is the item's ISBN or its URL if it has one and a blank node if
it has not.

Dublin Core has no vocabulary for a volume, an issue or a page range, and the
translator says so in a comment and drops them. That is the format rather than
an omission -- what is here is what an unqualified DC consumer can read.
"""

from collections.abc import Sequence

from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter
from altero.cite.formats.xmlwriter import Builder, Element

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC = "http://purl.org/dc/elements/1.1/"


def _description(item: ExportItem, index: int) -> Element:
    inside = Builder()

    inside.add("dc:title", item.get("title"))
    inside.add("dc:type", item.item_type)

    for creator in item.creators:
        # `lastName, firstName`, which Dublin Core does not prescribe and every
        # reader of it expects.
        name = "dc:creator" if creator.creator_type == "author" else "dc:contributor"
        inside.add(name, creator.name)

    inside.add("dc:source", item.get("source"))
    # An accession number is the identifier a catalogue gave the thing.
    inside.add("dc:identifier", item.get("accessionNumber"))
    inside.add("dc:rights", item.get("rights"))
    inside.add("dc:publisher", item.get("publisher", "distributor", "institution"))
    inside.add("dc:date", item.get("date"))

    for label, name in (("ISBN", "ISBN"), ("ISSN", "ISSN"), ("DOI", "DOI")):
        inside.add("dc:identifier", f"{label} {item.get(name)}" if item.get(name) else "")

    inside.add("dc:identifier", item.get("callNumber"))
    inside.add("dc:coverage", item.get("archiveLocation"))
    # `medium` belongs to the qualified terms, so unqualified DC calls it the
    # format, which is the translator's own reasoning and its own comment.
    inside.add("dc:format", item.get("medium"))

    isbn, url = item.get("ISBN"), item.get("url")
    if isbn:
        subject = ("rdf:about", f"urn:isbn:{isbn}")
    elif url:
        subject = ("rdf:about", url)
    else:
        # Nothing identifies this item outside the library it came from, so it
        # is a node with an id and no address, which is what RDF has them for.
        subject = ("rdf:nodeID", f"item_{index}")
    return inside.build("rdf:Description", subject)


class RdfDublinCore(TextWriter):
    """Unqualified Dublin Core RDF."""

    def __init__(self) -> None:
        self.written = 0

    def begin(self) -> str:
        return f'<rdf:RDF\n xmlns:rdf="{RDF}"\n xmlns:dc="{DC}">\n'

    def entries(self, items: Sequence[ExportItem]) -> str:
        rendered = []
        for item in items:
            self.written += 1
            rendered.append(_description(item, self.written).render(depth=1))
        return "".join(rendered)

    def end(self) -> str:
        return "</rdf:RDF>\n"
