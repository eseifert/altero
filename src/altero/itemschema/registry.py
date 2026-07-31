"""Reading of the vendored Zotero item type schema."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from altero.errors import InvalidInputError

#: The vendored copy of https://api.zotero.org/schema.
SCHEMA_PATH = Path(__file__).parent / "data" / "schema.json"

#: Locale used when the requested one is unknown.
DEFAULT_LOCALE = "en-US"

#: Item types that exist in the schema but are not offered by ``/itemTypes``.
#: Annotations and attachments are created through dedicated flows instead.
HIDDEN_ITEM_TYPES = frozenset({"annotation", "attachment"})

#: Creator name fields. These carry no translations in the schema, so the API
#: returns the same English labels for every locale.
CREATOR_FIELDS: tuple[tuple[str, str], ...] = (
    ("firstName", "First"),
    ("lastName", "Last"),
    ("name", "Name"),
)

#: Keys appended to every item template, with their empty values.
_TEMPLATE_SUFFIX: tuple[tuple[str, Any], ...] = (
    ("tags", []),
    ("collections", []),
    ("relations", {}),
)

#: Keys of an attachment template, per link mode, in the order the API emits them.
#: Attachments do not follow the schema's field list, so the shapes are explicit.
_ATTACHMENT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "imported_file": (
        "title",
        "accessDate",
        "note",
        *(name for name, _ in _TEMPLATE_SUFFIX),
        "contentType",
        "charset",
        "filename",
        "md5",
        "mtime",
    ),
    "imported_url": (
        "title",
        "accessDate",
        "url",
        "note",
        *(name for name, _ in _TEMPLATE_SUFFIX),
        "contentType",
        "charset",
        "filename",
        "md5",
        "mtime",
    ),
    "linked_file": (
        "title",
        "accessDate",
        "note",
        *(name for name, _ in _TEMPLATE_SUFFIX),
        "contentType",
        "charset",
        "path",
    ),
    "linked_url": (
        "title",
        "accessDate",
        "url",
        "note",
        *(name for name, _ in _TEMPLATE_SUFFIX),
        "contentType",
        "charset",
    ),
}

#: Attachment template keys that default to null rather than an empty string.
_NULL_DEFAULTS = frozenset({"md5", "mtime"})

#: Creator type seeded into ``/items/new`` for types where it differs from the
#: schema's primary one. Upstream marks ``creator`` primary for these two and
#: reports it from ``/itemTypeCreatorTypes``, yet seeds templates with
#: ``director``; the discrepancy is reproduced so templates stay interchangeable.
TEMPLATE_CREATOR_TYPES: dict[str, str] = {
    "radioBroadcast": "director",
    "videoRecording": "director",
}


@dataclass(frozen=True, slots=True)
class Field:
    """A field accepted by an item type."""

    name: str
    base_field: str | None = None


@dataclass(frozen=True, slots=True)
class CreatorType:
    """A creator type accepted by an item type."""

    name: str
    primary: bool = False


@dataclass(frozen=True, slots=True)
class ItemType:
    """One item type and everything it accepts, in schema order."""

    name: str
    fields: tuple[Field, ...]
    creator_types: tuple[CreatorType, ...]

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset(field.name for field in self.fields)

    @property
    def creator_type_names(self) -> frozenset[str]:
        return frozenset(creator.name for creator in self.creator_types)

    @property
    def primary_creator_type(self) -> str | None:
        for creator in self.creator_types:
            if creator.primary:
                return creator.name
        return self.creator_types[0].name if self.creator_types else None


class Schema:
    """The parsed schema, answering the questions the API and validation ask."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.version: int = raw["version"]
        self.item_types: dict[str, ItemType] = {
            entry["itemType"]: ItemType(
                name=entry["itemType"],
                fields=tuple(
                    Field(field["field"], field.get("baseField")) for field in entry["fields"]
                ),
                creator_types=tuple(
                    CreatorType(creator["creatorType"], creator.get("primary", False))
                    for creator in entry.get("creatorTypes", [])
                ),
            )
            for entry in raw["itemTypes"]
        }
        self._locales: dict[str, dict[str, dict[str, str]]] = raw["locales"]

    # -- locales ---------------------------------------------------------

    def resolve_locale(self, locale: str | None) -> str:
        """Return the closest locale the schema carries translations for.

        An exact match wins; otherwise any locale sharing the same language is
        used, so ``de-DE`` resolves to the schema's ``de``. Unknown locales fall
        back to English rather than failing.
        """
        if not locale:
            return DEFAULT_LOCALE
        if locale in self._locales:
            return locale

        language = locale.partition("-")[0].lower()
        for candidate in self._locales:
            if candidate.partition("-")[0].lower() == language:
                return candidate
        return DEFAULT_LOCALE

    def _translations(self, kind: str, locale: str | None) -> dict[str, str]:
        return self._locales[self.resolve_locale(locale)][kind]

    # -- lookups ---------------------------------------------------------

    def get_item_type(self, name: str) -> ItemType:
        """Return the named item type, or report it as invalid input."""
        item_type = self.item_types.get(name)
        if item_type is None:
            raise InvalidInputError(f"Invalid item type '{name}'")
        return item_type

    def is_valid_item_type(self, name: str) -> bool:
        return name in self.item_types

    @property
    def field_names(self) -> frozenset[str]:
        """Every field name that some item type accepts directly."""
        return frozenset(
            field.name for item_type in self.item_types.values() for field in item_type.fields
        )

    @property
    def base_field_names(self) -> frozenset[str]:
        """Names that only ever appear as the base of another field, such as ``medium``."""
        bases = {
            field.base_field
            for item_type in self.item_types.values()
            for field in item_type.fields
            if field.base_field
        }
        return frozenset(bases) - self.field_names

    @property
    def all_field_names(self) -> frozenset[str]:
        """Every field name, including base fields. Writes accept both forms."""
        return self.field_names | self.base_field_names

    # -- endpoint payloads -----------------------------------------------

    def localized_item_types(self, locale: str | None = None) -> list[dict[str, str]]:
        """Return the item types offered to clients, ordered by localized name."""
        names = self._translations("itemTypes", locale)
        entries = [
            {"itemType": name, "localized": names.get(name, name)}
            for name in self.item_types
            if name not in HIDDEN_ITEM_TYPES
        ]
        return sorted(entries, key=lambda entry: entry["localized"])

    def localized_fields(self, locale: str | None = None) -> list[dict[str, str]]:
        """Return every directly usable field, ordered by localized name.

        Base fields that no item type accepts on their own, such as ``medium``,
        are left out, matching the API. Fields that share a localized name (three
        of them are called "Format") may come out in a different order from the
        live API, which breaks the tie on an internal identifier not present in
        the published schema.
        """
        names = self._translations("fields", locale)
        entries = [{"field": name, "localized": names.get(name, name)} for name in self.field_names]
        return sorted(entries, key=lambda entry: entry["localized"])

    def localized_item_type_fields(
        self, item_type: str, locale: str | None = None
    ) -> list[dict[str, str]]:
        """Return the fields of one item type, in schema order."""
        names = self._translations("fields", locale)
        return [
            {"field": field.name, "localized": names.get(field.name, field.name)}
            for field in self.get_item_type(item_type).fields
        ]

    def localized_item_type_creator_types(
        self, item_type: str, locale: str | None = None
    ) -> list[dict[str, str]]:
        """Return the creator types of one item type.

        The primary type comes first and the rest follow in localized-name order,
        which is not the order the schema lists them in.
        """
        names = self._translations("creatorTypes", locale)
        type_ = self.get_item_type(item_type)
        primary = type_.primary_creator_type

        entries = [
            {"creatorType": creator.name, "localized": names.get(creator.name, creator.name)}
            for creator in type_.creator_types
            if creator.name != primary
        ]
        entries.sort(key=lambda entry: entry["localized"])

        if primary is not None:
            entries.insert(0, {"creatorType": primary, "localized": names.get(primary, primary)})
        return entries

    def localized_creator_fields(self, locale: str | None = None) -> list[dict[str, str]]:
        """Return the creator name fields."""
        return [{"field": name, "localized": label} for name, label in CREATOR_FIELDS]

    def template(self, item_type: str, link_mode: str | None = None) -> dict[str, Any]:
        """Return an empty item of the given type, as ``/items/new`` serves it."""
        type_ = self.get_item_type(item_type)

        if item_type == "attachment":
            return self._attachment_template(link_mode)

        template: dict[str, Any] = {"itemType": item_type}

        if item_type == "note":
            template["note"] = ""
        else:
            fields = list(type_.fields)
            # `creators` sits directly after the type's title field, which is
            # always the first one the schema lists.
            if fields:
                template[fields[0].name] = ""
            primary = TEMPLATE_CREATOR_TYPES.get(item_type, type_.primary_creator_type)
            if primary:
                template["creators"] = [{"creatorType": primary, "firstName": "", "lastName": ""}]
            for field in fields[1:]:
                template[field.name] = ""

        template.update(dict(_TEMPLATE_SUFFIX))
        return template

    def _attachment_template(self, link_mode: str | None) -> dict[str, Any]:
        if not link_mode:
            raise InvalidInputError("linkMode required for itemType=attachment")

        keys = _ATTACHMENT_TEMPLATES.get(link_mode)
        if keys is None:
            raise InvalidInputError(f"Invalid linkMode '{link_mode}'")

        template: dict[str, Any] = {"itemType": "attachment", "linkMode": link_mode}
        defaults = dict(_TEMPLATE_SUFFIX)
        for key in keys:
            if key in defaults:
                template[key] = [] if isinstance(defaults[key], list) else {}
            elif key in _NULL_DEFAULTS:
                template[key] = None
            else:
                template[key] = ""
        return template


@lru_cache(maxsize=1)
def get_schema() -> Schema:
    """Return the parsed schema, reading it from disk on first use."""
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return Schema(json.load(handle))
