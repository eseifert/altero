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
from collections import OrderedDict, defaultdict

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


#: Duplicate sets already worked out, by library and library version. The
#: version moves with every write to the library, so an entry is exact for as
#: long as it is asked for; paging through the view no longer redoes the whole
#: comparison for every page. Per process, like the streaming broker.
_FOUND: OrderedDict[tuple[int, int], tuple[tuple[int, ...], ...]] = OrderedDict()

#: How many libraries' sets are kept.
_KEPT = 16


def forget(library_id: int) -> None:
    """Drop what is remembered for ``library_id``.

    For a restore, which sets the version counter from the archive: a version
    the library had before can come back with different items behind it.
    """
    for found in [entry for entry in _FOUND if entry[0] == library_id]:
        del _FOUND[found]


def reset() -> None:
    """Forget every library, for a test whose database is new."""
    _FOUND.clear()


async def duplicate_item_ids(session: AsyncSession, library: Library) -> set[int]:
    """Return the ids of every item in ``library`` that has a duplicate.

    One pass over the library's own rows rather than a query per item: the
    comparison is between items, so there is no predicate to hand a database
    that would not first have to read the same three columns of every row.
    """
    return {item_id for group in await duplicate_item_groups(session, library) for item_id in group}


async def duplicate_item_groups(
    session: AsyncSession, library: Library
) -> tuple[tuple[int, ...], ...]:
    """Connected candidate groups, with oldest members first; cached per watermark."""
    remembered = (library.id, library.version)
    if (found := _FOUND.get(remembered)) is not None:
        _FOUND.move_to_end(remembered)
        return found
    found = await _find(session, library)
    _FOUND[remembered] = found
    while len(_FOUND) > _KEPT:
        _FOUND.popitem(last=False)
    return found


async def _find(session: AsyncSession, library: Library) -> tuple[tuple[int, ...], ...]:
    compared = select(Item.id).where(
        Item.library_id == library.id,
        Item.parent_id.is_(None),
        Item.deleted.is_(False),
        Item.item_type.not_in(UNCOMPARED),
    )
    candidates = list(await session.scalars(compared.order_by(Item.date_added, Item.key)))
    if len(candidates) < 2:
        return ()

    # The candidates are named by the query that found them rather than by
    # their ids, which in a large library are more than a statement can bind.
    field_rows = await session.execute(
        select(ItemField.item_id, ItemField.field, ItemField.value).where(
            ItemField.item_id.in_(compared), ItemField.field.in_(_FIELDS)
        )
    )
    fields: dict[int, dict[str, str]] = defaultdict(dict)
    for item_id, field, value in field_rows.all():
        fields[item_id][field] = value

    creator_rows = await session.execute(
        select(ItemCreator.item_id, ItemCreator.last_name, ItemCreator.name).where(
            ItemCreator.item_id.in_(compared)
        )
    )
    surnames: dict[int, set[str]] = defaultdict(set)
    for item_id, last_name, name in creator_rows.all():
        # A single-field creator is an organisation or a name nobody split;
        # the whole of it is what there is to compare.
        written = (last_name or name or "").strip().casefold()
        if written:
            surnames[item_id].add(written)

    parents = {item_id: item_id for item_id in candidates}

    def root(item_id: int) -> int:
        while parents[item_id] != item_id:
            parents[item_id] = parents[parents[item_id]]
            item_id = parents[item_id]
        return item_id

    def join(first: int, second: int) -> None:
        parents[root(second)] = root(first)

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
                for other in group[1:]:
                    join(group[0], other)

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
                    join(first, second)

    groups: dict[int, list[int]] = defaultdict(list)
    for item_id in candidates:
        groups[root(item_id)].append(item_id)
    return tuple(tuple(group) for group in groups.values() if len(group) > 1)


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
