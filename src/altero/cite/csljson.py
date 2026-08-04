"""Rendering stored items as CSL JSON.

The mapping itself is not invented here: the vendored schema carries the same
CSL tables Zotero uses, and :mod:`altero.itemschema` exposes them. What this
module contributes is the order the reference implementation applies them in --
one text variable takes the first field that has a value, creators fold onto CSL
name variables with the item type's primary creator becoming ``author``, and
dates go through the granularity-preserving parser in :mod:`altero.cite.dates`.
"""

import re
from typing import Any

from altero.itemschema import get_schema
from altero.models import Item, Library

from .dates import csl_date

#: A value wrapped in double quotes, which Zotero uses to mean "do not
#: re-order this" and which upstream strips before citing.
_QUOTED = re.compile(r'^"(.+)"$', re.DOTALL)


def _text_value(raw: str) -> str:
    match = _QUOTED.match(raw)
    return match.group(1) if match else raw


def _names(item: Item) -> dict[str, list[dict[str, str]]]:
    """Return the CSL name variables for an item's creators, in order.

    The item type's primary creator type becomes ``author`` whatever it is
    called -- an ``interviewee`` on an interview, a ``director`` on a film --
    because that is the role a style means by "author". Creator types the CSL
    map does not name are dropped rather than guessed at.
    """
    schema = get_schema()
    primary = (
        schema.get_item_type(item.item_type).primary_creator_type
        if schema.is_valid_item_type(item.item_type)
        else None
    )

    names: dict[str, list[dict[str, str]]] = {}
    for creator in item.creators:
        role = "author" if creator.creator_type == primary else creator.creator_type
        variable = schema.csl_names.get(role)
        if variable is None:
            continue
        # A single-field name is stored as the whole name; upstream passes it
        # through as the family name rather than as a CSL literal.
        name = (
            {"family": creator.name, "given": ""}
            if creator.name is not None
            else {"family": creator.last_name or "", "given": creator.first_name or ""}
        )
        names.setdefault(variable, []).append(name)
    return names


def csl_item(item: Item, library: Library) -> dict[str, Any]:
    """Return one item as a CSL JSON object.

    The ``id`` is the library's numeric id and the item key joined by a slash,
    which is what the reference implementation emits and what a client uses to
    match a rendered entry back to an item.
    """
    schema = get_schema()
    stored = item.field_values()

    csl: dict[str, Any] = {
        "id": f"{library.id}/{item.key}",
        "type": schema.csl_types.get(item.item_type, "document"),
    }

    for variable, candidates in schema.csl_text_fields:
        for candidate in candidates:
            field = schema.field_for(item.item_type, candidate) or candidate
            value = stored.get(field, "")
            if value:
                csl[variable] = _text_value(value)
                break

    csl.update(_names(item))

    for variable, candidate in schema.csl_date_fields:
        field = schema.field_for(item.item_type, candidate) or candidate
        if date := csl_date(stored.get(field, "")):
            csl[variable] = date

    return csl


def csl_items(items: list[Item], library: Library) -> list[dict[str, Any]]:
    """Return a page of items as CSL JSON objects."""
    return [csl_item(item, library) for item in items]
