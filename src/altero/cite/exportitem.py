"""What an export format is handed, and where it comes from.

Upstream exports by posting each item's API JSON to a translation server, which
hands it to the same JavaScript translator the desktop client runs -- so a
translator reads an item, not a citation. The formats here read the same thing:
this module is the Python side of what `Zotero.Utilities.Internal
.itemToExportFormat` builds for them, which is the API's item JSON with three
things added.

**Base fields are aliased onto their own names.** A `bookSection` stores its
container as `bookTitle` and a `journalArticle` as `publicationTitle`, both of
which are the base field `publicationTitle`; a translator asks for the base name
and expects an answer whatever the item type is. So does the other direction --
`Zotero RDF` asks for `bookTitle` -- so both names carry the value.

**A single-field creator is a last name.** The client sets `fieldMode` and moves
`name` into `lastName`; every export translator reads `lastName` and checks
`fieldMode` to decide whether a comma belongs.

**`versionNumber` is called `version`.** It was renamed in the item schema and
the translators were not, so the old name is what they still ask for.

The one thing not carried is child items. Upstream sends each item on its own,
so a translator's `item.notes` and `item.attachments` are empty there and are
empty here -- a note is exported as an item of its own or not at all.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from altero.cite.csljson import csl_item
from altero.itemschema import get_schema
from altero.models import Item, Library
from altero.serializers import library_prefix, ordered_fields, timestamp

#: Fields the export format knows by a name the schema no longer uses.
_RENAMED = {"versionNumber": "version"}


def _sql_stamp(value: str) -> str:
    """Return an API timestamp the way the client stores one: no `T`, no `Z`."""
    return value.replace("T", " ").rstrip("Z")


@dataclass(frozen=True, slots=True)
class Creator:
    """One creator, as a translator reads it."""

    creator_type: str
    first_name: str = ""
    last_name: str = ""
    #: A creator stored as one string rather than as a first/last pair. The
    #: translators call this `fieldMode 1` and use it to decide whether the name
    #: may be reordered or punctuated.
    single: bool = False

    @property
    def name(self) -> str:
        """Return the creator's name the way a bibliography lists it."""
        if self.single or not self.first_name:
            return self.last_name
        return f"{self.last_name}, {self.first_name}" if self.last_name else self.first_name

    @property
    def display_name(self) -> str:
        """Return the creator's name the way a sentence would write it."""
        if self.single or not self.first_name:
            return self.last_name
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(frozen=True, slots=True)
class ExportItem:
    """One item, in the shape the export formats read it in."""

    item_type: str
    key: str
    #: The item's address on this server, which is what upstream puts in the
    #: RDF and TEI identifiers. It names altero rather than zotero.org, for the
    #: reason `alternate` links are omitted altogether.
    uri: str
    fields: Mapping[str, str]
    #: The same fields under the names the API serves them by, with no aliases
    #: and no renaming. One translator reads these instead -- see :meth:`plain`.
    stored: Mapping[str, str] = field(default_factory=dict)
    #: One entry per stored field, under its base name where it has one and its
    #: own where it has not, in the schema's order. This is `uniqueFields`, and
    #: the two RDF formats walk it rather than asking for fields by name -- so
    #: what it holds and the order it holds it in are both the output.
    unique: Mapping[str, str] = field(default_factory=dict)
    creators: tuple[Creator, ...] = ()
    #: `(name, type)` pairs, type 0 being a tag somebody typed and 1 one that
    #: came with the item. CSV keeps the two apart; everything else does not.
    tags: tuple[tuple[str, int], ...] = ()
    #: SQL-shaped, as the export format has always had it: `2014-03-03 18:59:07`.
    date_added: str = ""
    #: ISO 8601 with a `Z`, which is the API's own shape. The two disagree
    #: upstream as well -- only `dateAdded` is converted -- and a CSV whose two
    #: date columns are written differently is what a reader has always got.
    date_modified: str = ""
    #: The same item as CSL JSON, for the formats mapped from a citation rather
    #: than from the item: BibTeX, BibLaTeX and RIS.
    csl: dict[str, Any] = field(default_factory=dict)

    def plain(self) -> ExportItem:
        """Return this item with its fields under the names the API uses.

        Zotero adds its compatibility mappings for translators written before
        4.0.27 and hands the later ones the item as it is. TEI is the only
        export translator on the far side of that line, and it shows: it reads
        `versionNumber` where the others read `version`, gets no `publisher` for
        a report -- whose field is `institution` -- and writes an access date
        with a `T` in it where the others write a space.
        """
        return replace(self, fields=self.stored)

    def get(self, *names: str) -> str:
        """Return the first of ``names`` this item has a value for."""
        for name in names:
            if value := self.fields.get(name, ""):
                return value
        return ""

    def creators_of(self, *types: str) -> list[Creator]:
        """Return the creators of the given types, in the order they are stored."""
        return [creator for creator in self.creators if creator.creator_type in types]

    @property
    def tag_names(self) -> list[str]:
        return [name for name, _ in self.tags]


def _base_fields(item_type: str) -> dict[str, str]:
    """Return each field of an item type that stands in for a base field."""
    schema = get_schema()
    if not schema.is_valid_item_type(item_type):
        return {}
    return {
        entry.name: entry.base_field
        for entry in schema.get_item_type(item_type).fields
        if entry.base_field
    }


def _unique_fields(item: Item) -> dict[str, str]:
    """Return an item's fields under their base names, in the schema's order."""
    bases = _base_fields(item.item_type)
    ordered = ordered_fields(item.item_type, item.field_values())
    unique = {
        _RENAMED.get(bases.get(name, name), bases.get(name, name)): value
        for name, value in ordered.items()
    }
    if access := unique.get("accessDate"):
        unique["accessDate"] = _sql_stamp(access)
    return unique


def _fields(item: Item) -> dict[str, str]:
    """Return an item's fields under both their own and their base names."""
    stored = item.field_values()
    values: dict[str, str] = {}

    bases = _base_fields(item.item_type)
    for name, value in stored.items():
        values[_RENAMED.get(name, name)] = value
        if base := bases.get(name):
            values.setdefault(base, value)

    # An attachment's content type is called `mimeType` by every translator
    # that looks at one, and `linkMode` is already stored under its own name.
    if content_type := stored.get("contentType"):
        values.setdefault("mimeType", content_type)

    # The one field whose shape the export format changes: `accessDate` is
    # stored and served as `2018-03-14T02:34:19Z` and read by the translators as
    # `2018-03-14 02:34:19`, several of which cut it at the space.
    if access := values.get("accessDate"):
        values["accessDate"] = _sql_stamp(access)
    return values


def export_item(
    item: Item,
    library: Library,
    base_url: str,
    tags: Sequence[tuple[str, int]] = (),
) -> ExportItem:
    """Return one stored item in the shape the export formats read."""
    return ExportItem(
        item_type=item.item_type,
        key=item.key,
        uri=f"{base_url}{library_prefix(library)}/items/{item.key}",
        fields=_fields(item),
        stored=item.field_values(),
        unique=_unique_fields(item),
        creators=tuple(
            Creator(
                creator_type=creator.creator_type,
                first_name=creator.first_name or "",
                last_name=creator.name or creator.last_name or "",
                single=creator.name is not None,
            )
            for creator in item.creators
        ),
        tags=tuple(tags),
        date_added=timestamp(item.date_added).replace("T", " ").rstrip("Z"),
        date_modified=timestamp(item.date_modified),
        csl=csl_item(item, library),
    )


def export_items(
    items: Sequence[Item],
    library: Library,
    base_url: str,
    tags: Mapping[int, list[tuple[str, int]]] | None = None,
) -> list[ExportItem]:
    """Return a page of stored items in the shape the export formats read."""
    tags = tags or {}
    return [export_item(item, library, base_url, tags.get(item.id, [])) for item in items]
