"""The export formats, and the one place that knows which of them exist.

Upstream produces every one of these by posting the items' API JSON to a
translation server running Zotero's own JavaScript translators. altero has no
such thing, so each format here is a port of the translator that writes it,
read out of `zotero/translators` and checked against what `api.zotero.org`
answers for the same item. Where a translator has a quirk -- a stray space, a
field written under the wrong name, a date that keeps two shapes -- the port
keeps it, because the point of the format is that another program reads it.

A format is a :class:`Writer` rather than a function because a file is written
in batches: exporting a library follows the query past the end of a page, and a
BibTeX citation key must stay unique across the whole file while an RDF
document has to open and close around all of it. So a writer is made once per
file, `begin` and `end` bracket it, and `write` is called with each batch.

This module deliberately stays out of :mod:`altero.cite`'s own ``__init__``:
the item view these formats read is built on :mod:`altero.serializers`, which
reaches back into the service layer, and importing that from the citation
package's front door would put a cycle in the import graph.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from altero.cite.exportitem import ExportItem
from altero.query import Format


class Writer(Protocol):
    """One file of exported items, written a batch at a time."""

    def begin(self) -> str:
        """Return whatever opens the file, before any item."""

    def accepts(self, item_type: str) -> bool:
        """Whether this format writes anything at all for items of this type."""

    def write(self, items: Sequence[ExportItem]) -> str:
        """Return one batch of items."""

    def end(self) -> str:
        """Return whatever closes the file, after the last item."""


#: Item types most formats have no entry for. A note is not a work, an
#: attachment is a file belonging to one, and an annotation belongs to the
#: attachment. Zotero's own translators skip the first two by name; the formats
#: that do write a note -- CSV, Zotero RDF, Evernote -- say so for themselves.
UNCITED_TYPES = frozenset({"note", "attachment", "annotation"})


class TextWriter:
    """A writer for the formats that are one entry after another.

    Subclasses implement :meth:`entries` and are handed only the items their
    format has something to say about, which is the whole of what `skips` is
    for: upstream's translators open with `if (item.itemType == "note") continue`
    and each has its own opinion about which types those are.
    """

    #: Item types this format writes nothing for.
    skips: frozenset[str] = UNCITED_TYPES

    def accepts(self, item_type: str) -> bool:
        """Whether this format has an entry for items of ``item_type``."""
        return item_type not in self.skips

    def begin(self) -> str:
        return ""

    def write(self, items: Sequence[ExportItem]) -> str:
        return self.entries([item for item in items if self.accepts(item.item_type)])

    def entries(self, items: Sequence[ExportItem]) -> str:
        """Return the accepted items, one entry after another."""
        raise NotImplementedError

    def end(self) -> str:
        return ""


@dataclass(frozen=True, slots=True)
class Kind:
    """What is known about one export format besides how to write it."""

    #: Made once per file; see the module docstring for why it is not a function.
    writer: Any
    #: Sent as ``Content-Type``, copied from what `api.zotero.org` answers with
    #: rather than from the dataserver's own table, which the translation server
    #: overrides for everything but a ``HEAD`` request.
    content_type: str
    #: What a downloaded file is called, from the translator's own `target`.
    extension: str


def _kinds() -> dict[Format, Kind]:
    """Return the registry, importing each format's module as it is built."""
    from altero.cite.formats import (
        bibliographic,
        bookmarks,
        coins,
        csvfile,
        endnotexml,
        evernote,
        rdfdc,
        refer,
        refworks,
        tei,
        wikipedia,
    )

    return {
        Format.BIBTEX: Kind(bibliographic.BibTeX, "application/x-bibtex", "bib"),
        Format.BIBLATEX: Kind(bibliographic.BibLaTeX, "application/x-bibtex", "bib"),
        Format.RIS: Kind(bibliographic.Ris, "application/x-research-info-systems", "ris"),
        Format.CSLJSON: Kind(
            bibliographic.CslJson, "application/vnd.citationstyles.csl+json", "json"
        ),
        Format.BOOKMARKS: Kind(bookmarks.Bookmarks, "text/html;charset=UTF-8", "html"),
        # The COinS translator declares no extension at all, having been written
        # for a page rather than for a file. A span of HTML is HTML.
        Format.COINS: Kind(coins.Coins, "text/html;charset=UTF-8", "html"),
        Format.CSV: Kind(csvfile.Csv, "text/csv;charset=UTF-8", "csv"),
        Format.ENDNOTE_XML: Kind(endnotexml.EndNoteXml, "text/xml;charset=UTF-8", "xml"),
        Format.EVERNOTE: Kind(evernote.Evernote, "text/xml;charset=UTF-8", "enex"),
        Format.RDF_DC: Kind(rdfdc.RdfDublinCore, "application/rdf+xml", "rdf"),
        Format.REFER: Kind(refer.Refer, "application/x-research-info-systems", "txt"),
        Format.REFWORKS_TAGGED: Kind(refworks.RefWorks, "text/plain;charset=UTF-8", "txt"),
        Format.TEI: Kind(tei.Tei, "text/xml;charset=UTF-8", "xml"),
        Format.WIKIPEDIA: Kind(wikipedia.Wikipedia, "text/x-wiki;charset=UTF-8", "txt"),
    }


_REGISTRY: dict[Format, Kind] | None = None


def kinds() -> dict[Format, Kind]:
    """Return every export format, by name."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _kinds()
    return _REGISTRY


def kind(response_format: Format) -> Kind:
    """Return one export format."""
    return kinds()[response_format]


def writer(response_format: Format) -> Writer:
    """Return a writer for one file in ``response_format``."""
    return kind(response_format).writer()


def render(response_format: Format, items: Sequence[ExportItem]) -> str:
    """Return ``items`` as one complete document.

    For a page of results and for the ``include`` values, both of which are one
    response rather than a file written in batches.
    """
    one = writer(response_format)
    body = one.write(items)
    return f"{one.begin()}{body}{one.end()}"
