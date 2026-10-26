"""What changing an item's type does to it, the way the desktop client does it.

A port of ``Zotero.Item.prototype.setType`` (``chrome/content/zotero/xpcom/
data/item.js``) and of the warning its item pane shows before calling it
(``itemBox.js``, ``changeTypeTo``). Upstream's server has a plainer version of
the same thing, :meth:`altero.itemschema.Schema.retype_fields`, for a client
that sends only the new type; the desktop does more, and a browser changing a
type should change it the way the application beside it would:

- a creator in the old type's primary role takes the new type's primary role
  rather than becoming a contributor, so a book's author is a film's director;
- a book's title becomes a book section's book title, and back again when the
  section has no title of its own, with the short title going either way.

Everything here is about values; nothing is written.
"""

from dataclasses import dataclass

from altero.errors import InvalidInputError
from altero.itemschema.registry import Schema

#: Types the desktop will not change to or from: their data is not fields.
SPECIAL_TYPES = frozenset({"note", "attachment", "annotation"})


@dataclass(frozen=True, slots=True)
class TypeChange:
    """The item as it will be after the change, and what the change costs."""

    #: Every non-empty field value of the new type.
    fields: dict[str, str]
    #: The creators, in order, with the roles they will have.
    creators: list[dict[str, str]]
    #: Fields whose values the change throws away, in the old type's order.
    lost: list[str]


def change_type(
    schema: Schema,
    old_type: str,
    new_type: str,
    values: dict[str, str],
    creators: list[dict[str, str]],
) -> TypeChange:
    """Change an item of ``old_type`` with ``values`` and ``creators`` to ``new_type``.

    Raises:
        InvalidInputError: if either type is a note, an attachment or an
            annotation, or ``new_type`` does not exist.
    """
    if old_type in SPECIAL_TYPES or new_type in SPECIAL_TYPES:
        raise InvalidInputError(f"Cannot change item type from '{old_type}' to '{new_type}'")
    new = schema.get_item_type(new_type)
    old = schema.get_item_type(old_type)
    present = {name: value for name, value in values.items() if value}

    result: dict[str, str] = {}
    cleared: set[str] = set()
    book_to_section = old_type == "book" and new_type == "bookSection"
    section_to_book = old_type == "bookSection" and new_type == "book"

    if section_to_book and present.get("bookTitle") and not present.get("title"):
        result["title"] = present["bookTitle"]
        cleared.add("shortTitle")

    lost: list[str] = []
    for name, value in present.items():
        if name in new.field_names:
            continue
        base = schema.base_of(old_type, name)
        target = schema.field_for(new_type, base) if base else None
        if target:
            result.setdefault(target, value)
        elif not (section_to_book and name == "bookTitle" and "title" in result):
            lost.append(name)

    if book_to_section and present.get("title"):
        result["bookTitle"] = present["title"]
        cleared.update({"title", "shortTitle"})

    for name, value in present.items():
        if name in new.field_names and name not in cleared:
            result.setdefault(name, value)

    # The item pane also warns about a short title it is about to clear, which
    # is not a field the new type lacks and so is not caught above.
    if "shortTitle" in cleared and present.get("shortTitle"):
        lost.append("shortTitle")

    old_primary = old.primary_creator_type
    new_primary = new.primary_creator_type
    valid = new.creator_type_names
    retyped = []
    for creator in creators:
        role = creator["creatorType"]
        if role not in valid:
            role = new_primary if role == old_primary and new_primary else "contributor"
        retyped.append({**creator, "creatorType": role})

    order = [field.name for field in old.fields]
    lost.sort(key=lambda name: order.index(name) if name in order else len(order))
    return TypeChange(
        fields={name: value for name, value in result.items() if name not in cleared},
        creators=retyped,
        lost=lost,
    )
