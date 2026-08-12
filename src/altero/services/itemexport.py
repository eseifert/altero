"""Writing a set of items out as a file for another program to read.

The formats themselves are :mod:`altero.cite.formats`, which the v3 API already
serves a page at a time. What this adds is everything that makes a *file* rather
than a response: it follows the query past the end of one page, so exporting a
library exports the library and not the first fifty of it; and it writes to disk
as it goes, because an export is as long as the library it came from and holding
one in memory is holding somebody's whole reading list twice over.

Batching is the reason a format is a writer rather than a function: a BibTeX
citation key is unique within a file and not within a call, an RDF document has
to open before the first item and close after the last, and a file written in
batches would otherwise start over at each one and hand out ``lovelace1994`` a
dozen times.
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from altero.cite import exportitem, formats
from altero.models import Item, Library
from altero.query import Format, ListQuery
from altero.services import items as items_service

#: Formats a set of items can be written out in: every export format, and CSL
#: JSON. `bib` is not among them -- a rendered bibliography is a document to
#: read rather than a file to hand to another program, and choosing one means
#: choosing a citation style, which is a question this has no way to ask.
EXPORT_FORMATS = frozenset(formats.kinds())

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
    return f"{stem or fallback}.{formats.kind(response_format).extension}"


async def _batch(
    session: AsyncSession,
    objects: Sequence[Item],
    library: Library,
    base_url: str,
    writer: formats.Writer,
) -> tuple[str, int]:
    """Return one batch of items written out, and how many entries that is.

    Tags are fetched here rather than read off the items, because a tag belongs
    to an item without being a field on it -- and every format that carries them
    calls them something else.
    """
    exportable = [item for item in objects if writer.accepts(item.item_type)]
    if not exportable:
        return "", 0

    stored = await items_service.tags_for(session, exportable)
    views = exportitem.export_items(exportable, library, base_url, stored)
    return writer.write(views), len(views)


async def write_items(
    session: AsyncSession,
    library: Library,
    destination: Path,
    *,
    base_url: str,
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
    writer = formats.writer(response_format)

    with destination.open("w", encoding="utf-8") as sink:
        sink.write(writer.begin())

        start = 0
        while True:
            page = await items_service.list_items(
                session, library, replace(query, limit=BATCH, start=start), scope, key
            )
            if not page.objects:
                break

            text, count = await _batch(session, page.objects, library, base_url, writer)
            sink.write(text)
            written += count

            fetched = len(page.objects)
            start += fetched
            for item in page.objects:
                session.expunge(item)
            if fetched < BATCH:
                break

        sink.write(writer.end())

    return written
