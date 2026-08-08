"""Finding the items in a library that are the same work twice.

The desktop client has a Duplicate Items row and works this out for itself, in
the copy of the library it holds; the dataserver has no endpoint for it and no
implementation to copy. So the rules here are altero's own, written to match
what the client is documented to do and what it visibly does, and recorded as a
divergence in ``docs/compatibility.md`` rather than presented as the client's
algorithm.

What is compared, and why:

* **DOI, then ISBN.** Two records carrying the same DOI are the same work,
  whatever else they disagree about, and that is the one comparison here that
  is an identity rather than a resemblance.
* **Title, with a creator or a year to back it up.** A title alone is not
  enough — "Introduction" and "Annual Report" are titles many works share — so
  a title match also needs a shared creator surname or the same year. Where
  neither record states a creator or a year, the title stands alone, which is
  the client's behaviour and is why two untitled-but-identical notes never
  appear here: notes and attachments are not compared at all.

What is deliberately *not* compared is the item type. A book and a book section
of the same title, by the same person, in the same year are exactly the pair
somebody wants to be shown, and refusing to look because the types differ would
hide it.
"""

import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, ItemCreator, ItemField, Library

#: Item types that are never compared. A note is its parent's, an attachment is
#: a file, and an annotation is a mark on a page: none of them is a work that
#: can be held twice.
UNCOMPARED = frozenset({"note", "attachment", "annotation"})

#: The fields read for the comparison, and nothing else.
_FIELDS = ("title", "DOI", "ISBN", "date", "caseName", "subject", "nameOfAct")

#: A title is compared with its punctuation and its casing taken off, because
#: two imports of one paper routinely disagree about both.
_NOISE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_title(value: str) -> str:
    """Return ``value`` reduced to what two records of one work would share."""
    folded = unicodedata.normalize("NFKD", value).casefold()
    return _SPACE.sub(" ", _NOISE.sub(" ", folded)).strip()


def normalise_identifier(value: str) -> str:
    """Return a DOI or ISBN with the punctuation and prefixes stripped off.

    ISBNs are written with and without hyphens and DOIs with and without the
    ``https://doi.org/`` in front of them, and neither difference is a
    difference between the works.
    """
    lowered = value.strip().casefold()
    lowered = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", "", lowered)
    # The dashes are the three an ISBN gets typed with: hyphen, en and em.
    return re.sub(r"[\s\-\u2013\u2014]", "", lowered)


def _year(date: str) -> str | None:
    """The four-digit year in a client-supplied date, if it holds one."""
    found = re.search(r"\d{4}", date)
    return found[0] if found else None


async def duplicate_item_ids(session: AsyncSession, library: Library) -> set[int]:
    """Return the ids of every item in ``library`` that has a duplicate.

    One pass over the library's own rows rather than a query per item: the
    comparison is between items, so there is no predicate to hand a database
    that would not first have to read the same three columns of every row.
    """
    rows = await session.execute(
        select(Item.id, Item.item_type).where(
            Item.library_id == library.id,
            Item.parent_id.is_(None),
            Item.deleted.is_(False),
        )
    )
    candidates = {item_id: kind for item_id, kind in rows.all() if kind not in UNCOMPARED}
    if len(candidates) < 2:
        return set()

    field_rows = await session.execute(
        select(ItemField.item_id, ItemField.field, ItemField.value).where(
            ItemField.item_id.in_(candidates), ItemField.field.in_(_FIELDS)
        )
    )
    fields: dict[int, dict[str, str]] = defaultdict(dict)
    for item_id, field, value in field_rows.all():
        fields[item_id][field] = value

    creator_rows = await session.execute(
        select(ItemCreator.item_id, ItemCreator.last_name, ItemCreator.name).where(
            ItemCreator.item_id.in_(candidates)
        )
    )
    surnames: dict[int, set[str]] = defaultdict(set)
    for item_id, last_name, name in creator_rows.all():
        # A single-field creator is an organisation or a name nobody split;
        # the whole of it is what there is to compare.
        written = (last_name or name or "").strip().casefold()
        if written:
            surnames[item_id].add(written)

    duplicates: set[int] = set()

    # The identifiers first, and on their own: two records with one DOI are the
    # same work even where every other field disagrees.
    for field in ("DOI", "ISBN"):
        by_identifier: dict[str, list[int]] = defaultdict(list)
        for item_id in candidates:
            value = normalise_identifier(fields[item_id].get(field, ""))
            if value:
                by_identifier[value].append(item_id)
        for group in by_identifier.values():
            if len(group) > 1:
                duplicates.update(group)

    # Then the titles, each group checked pair by pair for a creator or a year
    # to stand behind the title.
    by_title: dict[str, list[int]] = defaultdict(list)
    for item_id in candidates:
        stored = fields[item_id]
        written = stored.get("title") or stored.get("caseName") or stored.get("subject") or ""
        title = normalise_title(written)
        if title:
            by_title[title].append(item_id)

    for group in by_title.values():
        if len(group) < 2:
            continue
        for index, first in enumerate(group):
            for second in group[index + 1 :]:
                if _agrees(fields, surnames, first, second):
                    duplicates.update((first, second))

    return duplicates


def _agrees(
    fields: dict[int, dict[str, str]],
    surnames: dict[int, set[str]],
    first: int,
    second: int,
) -> bool:
    """Whether two same-titled items agree on a creator or a year.

    Where neither states one, the title is all there is and it is taken as
    enough: an item with no creator, no date and the same title as another is
    the case somebody imported twice.
    """
    if surnames[first] & surnames[second]:
        return True
    if surnames[first] and surnames[second]:
        return False

    years = [_year(fields[item].get("date", "")) for item in (first, second)]
    if years[0] and years[1]:
        return years[0] == years[1]
    return not (years[0] or years[1])
