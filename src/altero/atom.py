"""Rendering of the API's Atom feeds and entries.

Like :mod:`altero.serializers`, this module is free of web-framework imports:
callers hand over already-serialized JSON envelopes and a base URL, and receive
a string of XML.

The shapes here were read off the live API rather than off the prose, which
describes Atom only in outline. What upstream emits and altero does not is the
``rel="alternate"`` link, for the reason recorded in ``docs/compatibility.md``:
it names a page on zotero.org, and this server will not send a reader to
somebody else's copy of the data. The ``<id>`` of a feed and of an entry is
built on the address the request arrived on for the same reason.

The XML is written by hand rather than through :mod:`xml.etree.ElementTree`,
because an entry mixes three namespaces and embeds an XHTML fragment that
another component produced. A tree builder would either re-prefix that fragment
or refuse it; here it is checked for well-formedness once and then passed
through unchanged.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

from altero.errors import InvalidInputError
from altero.itemschema import get_schema
from altero.itemschema.registry import DEFAULT_LOCALE
from altero.models import Library, LibraryType

#: Namespaces an Atom document from this API uses.
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
ZAPI_NAMESPACE = "http://zotero.org/ns/api"
XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"

#: Media type of an Atom document. Upstream sends it without a charset.
CONTENT_TYPE = "application/atom+xml"

#: Values ``content`` accepts, and the ``include`` value each of them asks for.
#: ``html`` is rendered here rather than by the citation code, so it maps onto
#: no include value at all.
CONTENT_INCLUDES: dict[str, str | None] = {
    "html": None,
    "none": None,
    "json": "data",
    "bib": "bib",
    "citation": "citation",
    "csljson": "csljson",
    "bibtex": "bibtex",
    "biblatex": "biblatex",
    "ris": "ris",
}

#: Content values whose rendering is XHTML and so is embedded as markup.
_MARKUP_CONTENT = frozenset({"html", "bib", "citation"})

#: Content values an object without a citation form can be asked for. Upstream
#: neither documents nor obviously refuses ``content=bib`` on a collection; it
#: is rejected here rather than silently answered with an entry that has no
#: body, which a caller could not tell from a collection that has no citation.
NAMED_CONTENT_VALUES = frozenset({"html", "json", "none"})

#: Every content value the item endpoints accept.
ITEM_CONTENT_VALUES = frozenset(CONTENT_INCLUDES)

#: What a tag entry can be asked for. A tag is a name and a count, both of
#: which are already elements of the entry, so there is no body to render.
TAG_CONTENT_VALUES = frozenset({"html", "none"})

#: Media type written as the ``type`` attribute of a ``<content>`` that is not
#: XHTML. Upstream writes ``type="application/json"`` for a collection and
#: ``zapi:type="json"`` for an item, with neither carrying the other's
#: attribute; both are emitted here, so a consumer reading either finds it.
_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "csljson": "application/vnd.citationstyles.csl+json",
    "bibtex": "application/x-bibtex",
    "biblatex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
}

#: Display names for the fields the published schema does not list, which
#: :data:`altero.services.itemwrites.UNLISTED_FIELDS` lets through. Upstream
#: names the first three from its own internal field table; the rest are
#: altero's, since there is nothing to copy.
_UNLISTED_LABELS: dict[str, str] = {
    "linkMode": "Link Mode",
    "contentType": "MIME Type",
    "charset": "Character Set",
    "filename": "Filename",
    "md5": "MD5",
    "mtime": "Modification Time",
    "path": "Path",
    "lastRead": "Last Read",
    "note": "Note",
    "annotationType": "Annotation Type",
    "annotationAuthorName": "Annotation Author",
    "annotationText": "Annotation Text",
    "annotationComment": "Annotation Comment",
    "annotationColor": "Annotation Colour",
    "annotationPageLabel": "Annotation Page",
    "annotationSortIndex": "Annotation Sort Index",
    "annotationPosition": "Annotation Position",
}

#: Keys of an item's ``data`` that are not fields and so get no table row of
#: their own. ``inPublications`` does get one, under upstream's label.
_NON_FIELD_KEYS = frozenset(
    {
        "key",
        "version",
        "itemType",
        "parentItem",
        "creators",
        "tags",
        "collections",
        "relations",
        "deleted",
        "dateAdded",
        "dateModified",
        # The entry's own <title>, so upstream leaves it out of the table.
        "title",
    }
)

#: Longest title taken from a note, which has no title field of its own.
_NOTE_TITLE_LENGTH = 120


@dataclass(frozen=True, slots=True)
class Element:
    """One element of the document being written.

    ``markup`` is a serialized fragment emitted verbatim, which is how an XHTML
    body produced elsewhere reaches the output without being re-parsed.
    """

    name: str
    attributes: tuple[tuple[str, str], ...] = ()
    text: str | None = None
    children: tuple[Element, ...] = ()
    markup: str | None = None


@dataclass(frozen=True, slots=True)
class Author:
    """The ``<author>`` every feed and entry carries: the library it came from."""

    name: str
    uri: str


@dataclass(frozen=True, slots=True)
class Entry:
    """One ``<entry>``, before it is placed in a feed or served on its own."""

    title: str
    id: str
    self_url: str
    updated: str
    published: str | None = None
    up_url: str | None = None
    #: ``zapi:`` elements, in the order upstream emits them.
    properties: tuple[tuple[str, str], ...] = ()
    content: Element | None = None


def author_for(library: Library, base_url: str) -> Author:
    """Return the ``<author>`` describing ``library``."""
    prefix = "users" if library.type is LibraryType.USER else "groups"
    return Author(name=library.name, uri=f"{base_url}/{prefix}/{library.owner_id}")


def parse_content(
    value: str | None, accepted: frozenset[str] = ITEM_CONTENT_VALUES
) -> tuple[str, ...]:
    """Return the validated ``content`` set, in the order it is emitted.

    Sorted, because upstream sorts the ``zapi:subcontent`` elements of a
    multi-format entry and a consumer reading them positionally would otherwise
    depend on the order the parameter was written in. ``html`` is the default,
    as the documentation says.

    Args:
        accepted: The values this endpoint can produce.
    """
    if value is None or value == "":
        return ("html",)

    values = sorted({part for part in value.split(",") if part})
    for part in values:
        if part not in accepted:
            raise InvalidInputError(f"Invalid 'content' value '{part}'")
    if "none" in values and len(values) > 1:
        raise InvalidInputError("content=none is not valid in multi-format responses")
    return tuple(values) or ("html",)


# --------------------------------------------------------------------------
# Writing the document
# --------------------------------------------------------------------------


def _render(element: Element, depth: int = 0) -> str:
    """Return ``element`` as indented XML."""
    pad = "  " * depth
    attributes = "".join(f" {name}={quoteattr(value)}" for name, value in element.attributes)

    if element.markup is not None:
        body = "\n".join(f"{pad}  {line}" for line in element.markup.splitlines())
        return f"{pad}<{element.name}{attributes}>\n{body}\n{pad}</{element.name}>"

    if element.children:
        inner = "\n".join(_render(child, depth + 1) for child in element.children)
        return f"{pad}<{element.name}{attributes}>\n{inner}\n{pad}</{element.name}>"

    if element.text is None:
        return f"{pad}<{element.name}{attributes}/>"

    # Kept on one line: an Atom consumer reads the text content literally, and
    # indenting it would put whitespace inside a title or a JSON body.
    return f"{pad}<{element.name}{attributes}>{escape(element.text)}</{element.name}>"


def _document(root: Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + _render(root) + "\n"


def _link(rel: str, href: str) -> Element:
    return Element("link", (("rel", rel), ("type", CONTENT_TYPE), ("href", href)))


def _entry_element(entry: Entry, *, author: Author, root: bool) -> Element:
    """Return the ``<entry>`` for ``entry``.

    ``root`` adds the namespace declarations, which belong on the document
    element and so move to the feed when there is one.
    """
    attributes: list[tuple[str, str]] = []
    if root:
        attributes += [("xmlns", ATOM_NAMESPACE), ("xmlns:zapi", ZAPI_NAMESPACE)]

    children: list[Element] = [
        Element("title", text=entry.title),
        Element(
            "author",
            children=(Element("name", text=author.name), Element("uri", text=author.uri)),
        ),
        Element("id", text=entry.id),
    ]
    if entry.published:
        children.append(Element("published", text=entry.published))
    children.append(Element("updated", text=entry.updated))
    children.append(_link("self", entry.self_url))
    if entry.up_url:
        children.append(_link("up", entry.up_url))
    children += [Element(f"zapi:{name}", text=value) for name, value in entry.properties]
    if entry.content is not None:
        children.append(entry.content)

    return Element("entry", tuple(attributes), children=tuple(children))


def entry_document(entry: Entry, author: Author) -> str:
    """Return one entry as a document of its own, which is what a ``GET`` of a
    single object answers with."""
    return _document(_entry_element(entry, author=author, root=True))


def feed(
    *,
    title: str,
    feed_id: str,
    self_url: str,
    links: Mapping[str, str],
    entries: Sequence[Entry],
    author: Author,
    updated: str,
) -> str:
    """Return a feed holding ``entries``.

    ``links`` are the paging relations, which are the same ones the ``Link``
    header carries. Upstream additionally emits ``rel="first"`` on the first
    page, where it would point at the page being read; altero's paging links
    are built once for both the header and the feed, so the two cannot
    disagree about what pages exist.
    """
    children: list[Element] = [
        Element("title", text=title),
        Element("id", text=feed_id),
        _link("self", self_url),
        *(_link(rel, href) for rel, href in links.items()),
        Element("updated", text=updated),
        *(_entry_element(entry, author=author, root=False) for entry in entries),
    ]
    return _document(
        Element(
            "feed",
            (("xmlns", ATOM_NAMESPACE), ("xmlns:zapi", ZAPI_NAMESPACE)),
            children=tuple(children),
        )
    )


def newest(entries: Sequence[Entry], fallback: str) -> str:
    """Return the feed's ``<updated>``: the newest its entries carry.

    A feed with no entries still needs one, since Atom requires the element;
    ``fallback`` is what it gets.
    """
    return max((entry.updated for entry in entries), default=fallback)


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------


def _is_well_formed(markup: str) -> bool:
    """Return whether ``markup`` can go into the document as XML.

    A bibliography comes out of citeproc as HTML, which is XHTML in every case
    seen so far but is not guaranteed to be. Checking rather than assuming is
    what keeps a stray unescaped ampersand from making the whole feed
    unparseable for the reader that asked for it.
    """
    try:
        ElementTree.fromstring(markup)
    except ElementTree.ParseError:
        return False
    return True


def _in_xhtml(markup: str) -> str:
    """Return ``markup`` as the single namespaced ``div`` Atom wants.

    A bibliography and a citation come out of the citation code as plain HTML
    with no namespace on them. Atom's ``type="xhtml"`` says the body *is* XHTML,
    so a reader that takes it at its word gets elements in no namespace at all.
    The declaration is added to the fragment's own ``div`` where it has one, and
    a wrapper is put round it where it does not -- a citation is a ``span``.
    """
    stripped = markup.strip()
    if f'xmlns="{XHTML_NAMESPACE}"' in stripped.split(">", 1)[0]:
        return stripped
    if stripped.startswith("<div") and not stripped.startswith("<div/"):
        head, _, rest = stripped.partition(">")
        return f'{head.rstrip("/")} xmlns="{XHTML_NAMESPACE}">{rest}'
    return f'<div xmlns="{XHTML_NAMESPACE}">{stripped}</div>'


def _body(kind: str, name: str, value: Any, markup: str) -> Element:
    """Return one ``<content>`` or ``<zapi:subcontent>`` holding ``kind``.

    Args:
        name: The element to build, which differs between a single-format entry
            and one member of a multi-format one.
        value: What the envelope holds for this format, ignored for ``html``.
        markup: The rendered XHTML, for ``html``.
    """
    if kind == "html":
        return Element(name, (("zapi:type", "html"), ("type", "xhtml")), markup=markup)

    if kind in _MARKUP_CONTENT and isinstance(value, str):
        if _is_well_formed(value):
            return Element(name, (("zapi:type", kind), ("type", "xhtml")), markup=_in_xhtml(value))
        # Escaped instead, and labelled as escaped HTML. The reader still gets
        # the text; what it does not get is a document it cannot parse.
        return Element(name, (("zapi:type", kind), ("type", "html")), text=value)

    attributes = [("zapi:type", kind)]
    if media_type := _CONTENT_TYPES.get(kind):
        attributes.append(("type", media_type))
    return Element(name, tuple(attributes), text=_as_text(kind, value))


def _as_text(kind: str, value: Any) -> str:
    if value is None:
        return ""
    if kind in ("json", "csljson"):
        return json.dumps(value, indent=4, ensure_ascii=False)
    return str(value)


def _content(envelope: Mapping[str, Any], content: Sequence[str], markup: str) -> Element | None:
    """Return the ``<content>`` an entry carries, if any."""
    if content == ("none",):
        return Element("content", (("zapi:type", "none"),))

    def value_of(kind: str) -> Any:
        include = CONTENT_INCLUDES[kind]
        return envelope.get(include) if include else None

    if len(content) == 1:
        return _body(content[0], "content", value_of(content[0]), markup)

    return Element(
        "content",
        (("type", "application/xml"),),
        children=tuple(_body(kind, "zapi:subcontent", value_of(kind), markup) for kind in content),
    )


def item_content(
    envelope: Mapping[str, Any], content: Sequence[str], *, locale: str = DEFAULT_LOCALE
) -> Element | None:
    """Return the ``<content>`` an item entry carries.

    ``envelope`` is the JSON envelope the item endpoints already build, with
    whichever rendered forms ``include`` put on it. Producing the Atom body from
    that rather than from the item again is what keeps ``format=atom&content=bib``
    and ``format=json&include=bib`` from drifting apart.
    """
    markup = item_xhtml(envelope, locale=locale) if "html" in content else ""
    return _content(envelope, content, markup)


def item_xhtml(envelope: Mapping[str, Any], *, locale: str = DEFAULT_LOCALE) -> str:
    """Return the XHTML table ``content=html`` shows for an item.

    A row per field, under the name the schema gives it, in the order the
    item's own JSON emits them. Upstream orders them by an internal field
    identifier that the published schema does not carry, so the order cannot be
    reproduced -- the same limitation ``docs/compatibility.md`` records for
    fields that share a localized name.
    """
    data = envelope.get("data") or {}
    names = get_schema().display_names(locale)
    rows: list[str] = []

    item_type = data.get("itemType", "")
    rows.append(
        _row(
            "itemType",
            names["fields"].get("itemType", "Item Type"),
            names["itemTypes"].get(item_type, item_type),
        )
    )

    for creator in data.get("creators") or []:
        creator_type = creator.get("creatorType", "")
        label = names["creatorTypes"].get(creator_type, creator_type)
        rows.append(_row("creator", label, _creator_name(creator)))

    for name, value in data.items():
        if name in _NON_FIELD_KEYS:
            continue
        if name == "inPublications":
            rows.append(_row("publications", "In My Publications", "Yes" if value else "No"))
            continue
        if value in (None, ""):
            continue
        label = names["fields"].get(name) or _UNLISTED_LABELS.get(name, name)
        rows.append(_row(name, label, _display(name, value)))

    body = "\n".join(rows)
    return f'<div xmlns="{XHTML_NAMESPACE}">\n  <table>\n{body}\n  </table>\n</div>'


def _row(class_name: str, label: str, value: str) -> str:
    return (
        f'    <tr class="{escape(class_name)}">\n'
        f'      <th style="text-align: right">{escape(label)}</th>\n'
        f"      <td>{escape(value)}</td>\n"
        f"    </tr>"
    )


def _creator_name(creator: Mapping[str, Any]) -> str:
    if "name" in creator:
        return str(creator["name"])
    return " ".join(part for part in (creator.get("firstName"), creator.get("lastName")) if part)


def _display(name: str, value: Any) -> str:
    """Return a field's value as the table shows it.

    Timestamps lose the ``T`` and the ``Z``, which is how upstream writes an
    access date in this table: it is a value to read rather than one to parse.
    """
    text = str(value)
    if name.endswith("Date") or name == "accessDate":
        return text.replace("T", " ").removesuffix("Z")
    return text


# --------------------------------------------------------------------------
# Entries, per object kind
# --------------------------------------------------------------------------


def _entry_title(data: Mapping[str, Any]) -> str:
    """Return the title an item entry carries.

    A note has no title field, so its first line stands in -- which is what the
    desktop client shows in the same position.
    """
    if title := data.get("title"):
        return str(title)
    if note := data.get("note"):
        text = re.sub(r"<[^>]+>", " ", str(note))
        text = " ".join(text.split())
        return text[:_NOTE_TITLE_LENGTH]
    return ""


def content_suffix(content: Sequence[str]) -> str:
    """Return the ``&content=`` an entry's own links carry.

    Omitted for the default, which is how upstream writes the link of an entry
    the client asked nothing particular of.
    """
    if not content or tuple(content) == ("html",):
        return ""
    return "&" + urlencode({"content": ",".join(content)})


def item_entry(
    envelope: Mapping[str, Any],
    content: Sequence[str],
    *,
    locale: str = DEFAULT_LOCALE,
) -> Entry:
    """Return the entry for one serialized item."""
    query_suffix = content_suffix(content)
    data = envelope.get("data") or {}
    meta = envelope.get("meta") or {}
    links = envelope.get("links") or {}
    self_href = links.get("self", {}).get("href", "")
    up_href = links.get("up", {}).get("href")

    properties: list[tuple[str, str]] = [
        ("key", str(envelope.get("key", ""))),
        ("version", str(envelope.get("version", 0))),
        ("itemType", str(data.get("itemType", ""))),
    ]
    if summary := meta.get("creatorSummary"):
        properties.append(("creatorSummary", str(summary)))
    if parsed := meta.get("parsedDate"):
        properties.append(("parsedDate", str(parsed)))
    # Only for a top-level item, as upstream does: a child item's own children
    # are not a thing the data model has.
    if not data.get("parentItem"):
        properties.append(("numChildren", str(meta.get("numChildren", 0))))

    return Entry(
        title=_entry_title(data),
        id=self_href,
        self_url=f"{self_href}?format=atom{query_suffix}",
        up_url=f"{up_href}?format=atom{query_suffix}" if up_href else None,
        published=str(data.get("dateAdded", "")) or None,
        updated=str(data.get("dateModified", "")),
        properties=tuple(properties),
        content=item_content(envelope, content, locale=locale),
    )


def _named_content(envelope: Mapping[str, Any], content: Sequence[str]) -> Element | None:
    """Return the body of a collection or saved search entry.

    ``html`` produces no element at all, which is what upstream sends: neither
    object has a rendering, and an empty one would claim it did.
    """
    if content == ("html",):
        return None
    return _content(envelope, content, "")


def collection_entry(
    envelope: Mapping[str, Any], content: Sequence[str], *, timestamps: tuple[str, str]
) -> Entry:
    """Return the entry for one serialized collection.

    Collections carry no timestamps in their JSON envelope -- the API does not
    publish them -- so the caller supplies them from the stored object.
    """
    meta = envelope.get("meta") or {}
    self_href = (envelope.get("links") or {}).get("self", {}).get("href", "")
    added, modified = timestamps

    return Entry(
        title=str((envelope.get("data") or {}).get("name", "")),
        id=self_href,
        self_url=f"{self_href}?format=atom",
        published=added,
        updated=modified,
        properties=(
            ("key", str(envelope.get("key", ""))),
            ("version", str(envelope.get("version", 0))),
            ("numCollections", str(meta.get("numCollections", 0))),
            ("numItems", str(meta.get("numItems", 0))),
        ),
        content=_named_content(envelope, content),
    )


def search_entry(
    envelope: Mapping[str, Any], content: Sequence[str], *, timestamps: tuple[str, str]
) -> Entry:
    """Return the entry for one serialized saved search."""
    self_href = (envelope.get("links") or {}).get("self", {}).get("href", "")
    added, modified = timestamps

    return Entry(
        title=str((envelope.get("data") or {}).get("name", "")),
        id=self_href,
        self_url=f"{self_href}?format=atom",
        published=added,
        updated=modified,
        properties=(
            ("key", str(envelope.get("key", ""))),
            ("version", str(envelope.get("version", 0))),
        ),
        content=_named_content(envelope, content),
    )


def tag_entry(envelope: Mapping[str, Any], content: Sequence[str], *, updated: str) -> Entry:
    """Return the entry for one serialized tag.

    A tag has no key, no version and no timestamps of its own; ``updated`` is
    the newest change to any item carrying it, which is the only sense in which
    a tag can be said to have changed. The empty XHTML body is upstream's: a
    tag is a name and a count, and both are already in the entry's own elements.
    """
    self_href = (envelope.get("links") or {}).get("self", {}).get("href", "")

    return Entry(
        title=str(envelope.get("tag", "")),
        id=self_href,
        self_url=self_href,
        updated=updated,
        properties=(("numItems", str((envelope.get("meta") or {}).get("numItems", 0))),),
        content=_content(envelope, content, f'<div xmlns="{XHTML_NAMESPACE}"/>'),
    )


def feed_id(url: str, params: Iterable[tuple[str, str]]) -> str:
    """Return a feed's ``<id>``.

    The request's own address without ``format``, which is what upstream builds
    it from -- on its own host, where altero uses the one the request arrived
    on rather than pointing the reader at zotero.org.

    Args:
        url: The request URL with its query string already stripped.
    """
    kept = sorted((name, value) for name, value in params if name != "format")
    query = f"?{urlencode(kept)}" if kept else ""
    return f"{url}{query}"
