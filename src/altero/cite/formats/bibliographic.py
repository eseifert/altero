"""The formats mapped from a citation rather than from the item.

BibTeX, BibLaTeX and RIS were altero's first three export formats and are
written from the CSL JSON an item renders as, in :mod:`altero.cite.export`.
What is here is the file around them: the citation keys that have to stay unique
across a whole export, and CSL JSON's brackets and commas, which belong to the
document rather than to any one entry.
"""

import json
import textwrap
from collections.abc import Sequence

from altero.cite.export import bibtex, ris
from altero.cite.exportitem import ExportItem
from altero.cite.formats import TextWriter


class BibTeX(TextWriter):
    """BibTeX, with citation keys unique across the file."""

    biblatex = False

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def entries(self, items: Sequence[ExportItem]) -> str:
        return bibtex(
            [item.csl for item in items],
            keywords=[item.tag_names for item in items],
            biblatex=self.biblatex,
            taken=self.taken,
        )


class BibLaTeX(BibTeX):
    """BibLaTeX, which differs from BibTeX in its entry types."""

    biblatex = True


class Ris(TextWriter):
    """RIS."""

    def entries(self, items: Sequence[ExportItem]) -> str:
        return ris([item.csl for item in items], keywords=[item.tag_names for item in items])


class CslJson(TextWriter):
    """CSL JSON as a file: one array, however many batches it took to write.

    Indented like the client's own CSL JSON translator, which writes a file
    people open and read as often as they feed it to something.
    """

    def __init__(self) -> None:
        self.written = 0

    def begin(self) -> str:
        return "[\n"

    def entries(self, items: Sequence[ExportItem]) -> str:
        if not items:
            return ""
        # The array is one document written in pieces, so the comma between two
        # batches is put in here along with the ones inside a batch.
        separator = ",\n" if self.written else ""
        self.written += len(items)
        return separator + ",\n".join(
            textwrap.indent(json.dumps(item.csl, ensure_ascii=False, indent=2), "  ")
            for item in items
        )

    def end(self) -> str:
        return "\n]\n" if self.written else "]\n"
