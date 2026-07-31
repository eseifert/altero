"""Derivation of an item's sort keys and display metadata.

Both the read path and the write path go through here, so a stored sort key and
the summary shown beside it can never disagree.
"""

import re
from collections.abc import Sequence

from altero.itemschema import get_schema
from altero.models import ItemCreator

#: Leading year, optionally followed by month and day.
_DATE_PATTERN = re.compile(r"\b(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?\b")


def title_field_for(item_type: str) -> str | None:
    """Return the field that acts as the title for ``item_type``.

    Most types call it ``title``; a few use their own name, such as ``caseName``,
    which the schema marks as being based on ``title``.
    """
    schema = get_schema()
    if not schema.is_valid_item_type(item_type):
        return None

    fields = schema.get_item_type(item_type).fields
    for field in fields:
        if field.name == "title" or field.base_field == "title":
            return field.name
    return None


def date_field_for(item_type: str) -> str | None:
    """Return the field that acts as the date for ``item_type``."""
    schema = get_schema()
    if not schema.is_valid_item_type(item_type):
        return None

    for field in schema.get_item_type(item_type).fields:
        if field.name == "date" or field.base_field == "date":
            return field.name
    return None


def derive_sort_title(item_type: str, fields: dict[str, str]) -> str:
    """Return the value items of this type are sorted by when sorting on title."""
    if item_type == "note":
        # A note has no title; Zotero shows the start of its content instead.
        note = fields.get("note", "")
        return re.sub(r"<[^>]+>", "", note).strip()[:500]

    field = title_field_for(item_type)
    return fields.get(field, "") if field else ""


def derive_sort_creator(creators: Sequence[ItemCreator]) -> str:
    """Return the value items are sorted by when sorting on creator."""
    return creators[0].sort_name if creators else ""


def derive_sort_date(item_type: str, fields: dict[str, str]) -> str:
    """Return the value items are sorted by when sorting on date."""
    field = date_field_for(item_type)
    return fields.get(field, "") if field else ""


def creator_summary(creators: Sequence[ItemCreator]) -> str:
    """Return the ``meta.creatorSummary`` shown for an item."""
    names = [creator.sort_name for creator in creators if creator.sort_name]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]} et al."


def parsed_date(raw: str) -> str | None:
    """Return the ``meta.parsedDate`` for a raw date value.

    Only the parts actually present are emitted, so a bare year stays a year.
    """
    match = _DATE_PATTERN.search(raw or "")
    if match is None:
        return None

    year, month, day = match.groups()
    if month and day:
        return f"{year}-{month}-{day}"
    if month:
        return f"{year}-{month}"
    return year
