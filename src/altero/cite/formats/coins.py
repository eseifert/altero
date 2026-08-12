"""COinS: an OpenURL context object per item, wrapped in a span.

A port of `COinS.js`, whose whole body is one call to
`Zotero.OpenURL.createContextObject` -- so most of this module is that function
rather than the translator. The context object is a query string of
`key=value` pairs, and the shape of it depends on the item type: a journal
article is described in the `journal` metadata format, books and their
relatives in `book`, a thesis and a patent in formats of their own, and
everything else falls back to Dublin Core.

This is the one format that writes something for every item it is given,
including a note: upstream emits a span carrying nothing but `rft.type=note`,
and a reader counting spans against items would otherwise come up short.
"""

from collections.abc import Sequence
from urllib.parse import quote

from altero.cite.dates import iso_date
from altero.cite.exportitem import Creator, ExportItem
from altero.cite.formats import TextWriter

#: What `encodeURIComponent` leaves alone. Python quotes a longer set by
#: default, and a context object is compared byte for byte by some resolvers.
_UNRESERVED = "-_.!~*'()"

#: Item types described in the `book` metadata format, and the genre each is
#: given. The order matters no more than the table does; the genre does.
_BOOK_TYPES = {
    "book": "book",
    "bookSection": "bookitem",
    "conferencePaper": "proceeding",
    "report": "report",
}

#: How Zotero's own escaping writes the five characters that matter in an
#: attribute. It differs from XML's only in `&apos;`, which is what the
#: translator produces and what the span is quoted with.
_HTML_ESCAPES = {"&": "&amp;", '"': "&quot;", "'": "&apos;", "<": "&lt;", ">": "&gt;"}


def _escape(value: str) -> str:
    """Return ``value`` escaped as `Zotero.Utilities.htmlSpecialChars` does."""
    return "".join(_HTML_ESCAPES.get(character, character) for character in value)


def _pmid(extra: str) -> str:
    """Return the PubMed id recorded in an item's `Extra` field, if any."""
    for line in extra.splitlines():
        label, separator, value = line.partition(":")
        if separator and label.strip() == "PMID" and value.strip().isdigit():
            return value.strip()
    return ""


class _ContextObject:
    """The `key=value` pairs of one context object, in the order they are made."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def add(self, value: str, tag: str, *, prefixed: bool = True) -> None:
        """Record one entry, or nothing at all when the value is empty."""
        if not value:
            return
        name = f"rft.{tag}" if prefixed else tag
        self.entries.append(f"{name}={quote(value, safe=_UNRESERVED)}")

    def __str__(self) -> str:
        return "&".join(self.entries)


def _first_creator(item: ExportItem) -> Creator | None:
    """Return the creator a context object names as the author.

    The item type's own primary creator, an `author` whatever the type calls
    its own, and an editor last -- which is the order
    `getFirstCreatorFromItemJSON` tries them in.
    """
    from altero.itemschema import get_schema

    schema = get_schema()
    primary = (
        schema.get_item_type(item.item_type).primary_creator_type
        if schema.is_valid_item_type(item.item_type)
        else None
    )
    for creator in item.creators:
        if creator.creator_type in {primary, "author"}:
            return creator
    return next((creator for creator in item.creators if creator.creator_type == "editor"), None)


def context_object(item: ExportItem) -> str:
    """Return the OpenURL 1.0 context object describing ``item``."""
    context = _ContextObject()
    context.add("Z39.88-2004", "url_ver", prefixed=False)
    context.add("Z39.88-2004", "ctx_ver", prefixed=False)
    context.add("info:sid/zotero.org:2", "rfr_id", prefixed=False)

    doi, isbn = item.get("DOI"), item.get("ISBN")
    if doi:
        context.add(f"info:doi/{doi}", "rft_id", prefixed=False)
    if isbn:
        context.add(f"urn:isbn:{isbn}", "rft_id", prefixed=False)
    if pmid := _pmid(item.get("extra")):
        context.add(f"info:pmid/{pmid}", "rft_id", prefixed=False)

    if item.item_type == "journalArticle":
        context.add("info:ofi/fmt:kev:mtx:journal", "rft_val_fmt", prefixed=False)
        context.add("article", "genre")
        context.add(item.get("title"), "atitle")
        context.add(item.get("publicationTitle"), "jtitle")
        context.add(item.get("journalAbbreviation"), "stitle")
        context.add(item.get("volume"), "volume")
        context.add(item.get("issue"), "issue")
    elif item.item_type in _BOOK_TYPES:
        context.add("info:ofi/fmt:kev:mtx:book", "rft_val_fmt", prefixed=False)
        context.add(_BOOK_TYPES[item.item_type], "genre")
        if item.item_type == "book":
            context.add(item.get("title"), "btitle")
        elif item.item_type == "report":
            context.add(item.get("seriesTitle"), "series")
            context.add(item.get("title"), "btitle")
        else:
            context.add(item.get("title"), "atitle")
            container = "proceedingsTitle" if item.item_type == "conferencePaper" else None
            context.add(item.get(container or "publicationTitle"), "btitle")
        context.add(item.get("place"), "place")
        context.add(item.get("publisher"), "publisher")
        context.add(item.get("edition"), "edition")
        context.add(item.get("series"), "series")
    elif item.item_type == "thesis":
        context.add("info:ofi/fmt:kev:mtx:dissertation", "rft_val_fmt", prefixed=False)
        context.add(item.get("title"), "title")
        context.add(item.get("publisher"), "inst")
        context.add(item.get("type"), "degree")
    elif item.item_type == "patent":
        context.add("info:ofi/fmt:kev:mtx:patent", "rft_val_fmt", prefixed=False)
        context.add(item.get("title"), "title")
        context.add(item.get("assignee"), "assignee")
        context.add(item.get("patentNumber"), "number")
        context.add(iso_date(item.get("issueDate")), "date")
    else:
        # Everything else is described in Dublin Core, which round-trips back
        # into Zotero because the type is carried as Zotero's own name for it.
        context.add("info:ofi/fmt:kev:mtx:dc", "rft_val_fmt", prefixed=False)
        context.add(item.item_type, "type")
        context.add(item.get("title"), "title")
        context.add(item.get("publicationTitle"), "source")
        context.add(item.get("rights"), "rights")
        context.add(item.get("publisher"), "publisher")
        context.add(item.get("abstractNote"), "description")
        if doi:
            context.add(f"urn:doi:{doi}", "identifier")
        elif url := item.get("url"):
            context.add(url, "identifier")

    if creator := _first_creator(item):
        if item.item_type == "patent":
            context.add(creator.first_name, "invfirst")
            context.add(creator.last_name, "invlast")
        else:
            # `aucorp`, for a creator that is an organisation, is not reachable
            # from here: it is decided by a flag the client sets while reading a
            # page and the API's item JSON does not carry, so a one-field name
            # arrives as a surname there as well.
            context.add(creator.first_name, "aufirst")
            context.add(creator.last_name, "aulast")

    author_tag = "inventor" if item.item_type == "patent" else "au"
    for creator in item.creators:
        context.add(creator.display_name, author_tag)

    # A patent's application date and its issue date are both written, the
    # second one twice: `date` above came from `issueDate`, and `date` is the
    # same field under its base name.
    context.add(iso_date(item.get("date")), "appldate" if item.item_type == "patent" else "date")

    if pages := item.get("pages"):
        context.add(pages, "pages")
        first, _, last = pages.replace("–", "-").partition("-")  # noqa: RUF001
        if last:
            context.add(first, "spage")
            context.add(last, "epage")

    context.add(item.get("numPages"), "tpages")
    context.add(isbn, "isbn")
    context.add(item.get("ISSN"), "issn")
    context.add(item.get("language"), "language")
    return str(context)


class Coins(TextWriter):
    """COinS."""

    #: Every item gets a span, a note and an attachment included.
    skips = frozenset()

    def entries(self, items: Sequence[ExportItem]) -> str:
        return "".join(
            f"<span class='Z3988' title='{_escape(context_object(item))}'></span>\n"
            for item in items
        )
