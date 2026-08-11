"""Writing a set of items out as a file for another program to read.

The formats are :mod:`altero.cite.export` and :mod:`altero.cite.csljson`, which
the v3 API already serves a page at a time. What this adds is everything that
makes a *file* rather than a response: it follows the query past the end of one
page, so exporting a library exports the library and not the first fifty of it;
it leaves out what has no bibliography entry; and it writes to disk as it goes,
because an export is as long as the library it came from and holding one in
memory is holding somebody's whole reading list twice over.

Batching is the reason :func:`altero.cite.bibtex` takes the set of citation keys
already used: a key is unique within a file, and a file written in batches would
otherwise start counting again at every batch and hand out ``lovelace1994`` a
dozen times.
"""

import json
import re
import textwrap
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from altero import cite
from altero.models import Item, Library
from altero.query import Format, ListQuery
from altero.services import items as items_service

#: Formats a set of items can be written out in. `bib` is not among them: a
#: rendered bibliography is a document to read rather than a file to hand to
#: another program, and choosing one means choosing a citation style, which is a
#: question this has no way to ask.
EXPORT_FORMATS = frozenset({Format.BIBTEX, Format.BIBLATEX, Format.RIS, Format.CSLJSON})

#: What a file of each is called, following the desktop client's translators:
#: both BibTeX flavours write `.bib`, and CSL JSON is JSON.
EXTENSIONS = {
    Format.BIBTEX: "bib",
    Format.BIBLATEX: "bib",
    Format.RIS: "ris",
    Format.CSLJSON: "json",
}

#: Item types no export format has an entry for. A note is not a work, an
#: attachment is a file belonging to one, and an annotation belongs to the
#: attachment -- the desktop client's own translators skip the first two and its
#: library export drops annotations before the translator ever sees them.
UNCITED_TYPES = frozenset({"note", "attachment", "annotation"})

#: How many items are read, rendered and written at a time. Large enough that a
#: library of a few thousand is a handful of queries, small enough that no
#: request holds more than a few megabytes of rendered text.
BATCH = 200

#: What may appear in the name of the file. Everything else is dropped rather
#: than replaced, the way the client's own `getValidFileName` does it: a name is
#: a label, and a label with the path separators taken out is still the label.
_NAME_CHARACTERS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: Longest name accepted, before the extension. Filesystems stop at 255 bytes;
#: this leaves room for the extension and for a name whose characters are not
#: one byte each.
_NAME_LIMIT = 80


def file_name(name: str | None, response_format: Format, fallback: str) -> str:
    """Return what to call the exported file, extension included.

    The name comes from the browser because that is where the view has a name:
    "My Library" in the reader's own language, or a collection's, or the client's
    "Exported Items" for a handful of rows picked out. It is a label chosen by
    the person exporting, exactly as the desktop client's file picker is -- so it
    is stripped of anything that would make it more than a label rather than
    refused.
    """
    stem = _NAME_CHARACTERS.sub("", name or "").strip().strip(".")[:_NAME_LIMIT].strip()
    return f"{stem or fallback}.{EXTENSIONS[response_format]}"


def _render(
    csl: Sequence[dict[str, Any]],
    keywords: Sequence[Sequence[str]],
    response_format: Format,
    taken: set[str],
) -> str:
    """Return one batch of items in ``response_format``."""
    if response_format is Format.RIS:
        return cite.ris(list(csl), keywords=keywords)
    if response_format is Format.CSLJSON:
        # Indented like the client's own CSL JSON translator, which writes a file
        # people open and read as often as they feed it to something.
        return ",\n".join(
            textwrap.indent(json.dumps(entry, ensure_ascii=False, indent=2), "  ") for entry in csl
        )
    return cite.bibtex(
        list(csl),
        keywords=keywords,
        biblatex=response_format is Format.BIBLATEX,
        taken=taken,
    )


async def _batch(
    session: AsyncSession,
    objects: Sequence[Item],
    library: Library,
    response_format: Format,
    taken: set[str],
) -> tuple[str, int]:
    """Return one batch of items written out, and how many entries that is.

    Tags come along as keywords, which BibTeX and RIS both carry and CSL does
    not -- so they are fetched here rather than read out of the CSL JSON, as the
    v3 export does it.
    """
    exportable = [item for item in objects if item.item_type not in UNCITED_TYPES]
    if not exportable:
        return "", 0

    stored = await items_service.tags_for(session, exportable)
    keywords = [[name for name, _ in stored.get(item.id, [])] for item in exportable]
    return (
        _render(cite.csl_items(exportable, library), keywords, response_format, taken),
        len(exportable),
    )


async def write_items(
    session: AsyncSession,
    library: Library,
    destination: Path,
    *,
    response_format: Format,
    query: ListQuery,
    scope: items_service.Scope = items_service.Scope.TOP,
    key: str | None = None,
) -> int:
    """Write every item ``query`` matches to ``destination``; return how many.

    ``query``'s own ``limit`` and ``start`` are ignored: the point of an export
    is that it does not stop at the end of a page. Each batch is detached from
    the session once it has been written, so the cost of exporting a library is
    the cost of one batch rather than of the library.
    """
    written = 0
    taken: set[str] = set()

    with destination.open("w", encoding="utf-8") as sink:
        if response_format is Format.CSLJSON:
            sink.write("[\n")

        start = 0
        while True:
            page = await items_service.list_items(
                session, library, replace(query, limit=BATCH, start=start), scope, key
            )
            if not page.objects:
                break

            text, count = await _batch(session, page.objects, library, response_format, taken)
            if text:
                if response_format is Format.CSLJSON and written:
                    # The array is one document written in pieces, so the comma
                    # between two batches is put in here; within a batch the
                    # renderer does it.
                    sink.write(",\n")
                sink.write(text)
            written += count

            fetched = len(page.objects)
            start += fetched
            for item in page.objects:
                session.expunge(item)
            if fetched < BATCH:
                break

        if response_format is Format.CSLJSON:
            sink.write("\n]\n" if written else "]\n")

    return written
