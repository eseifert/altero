"""BibTeX, BibLaTeX and RIS, written from the CSL JSON an item renders as.

Upstream hands the item JSON to a translation server running Zotero's own
JavaScript translators, which altero has no equivalent of. What it does have is
the CSL JSON conversion the citation formats already use, and CSL is a superset
of what these three formats carry -- so the export is a mapping exercise from
there rather than a second reading of the item.

The serialising is left to `bibtexparser` and `rispy`: brace balancing, tag
widths and line folding are exactly the sort of thing that looks simple and is
not.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

#: CSL type to BibTeX entry type. BibTeX's vocabulary is much smaller than
#: CSL's, so several types collapse onto `misc`, which is what every other
#: exporter does with them too.
_BIBTEX_TYPES = {
    "article-journal": "article",
    "article-magazine": "article",
    "article-newspaper": "article",
    "article": "article",
    "book": "book",
    "chapter": "incollection",
    "entry": "incollection",
    "entry-dictionary": "incollection",
    "entry-encyclopedia": "incollection",
    "paper-conference": "inproceedings",
    "manuscript": "unpublished",
    "report": "techreport",
    "thesis": "phdthesis",
    "webpage": "misc",
    "post": "misc",
    "post-weblog": "misc",
    "speech": "misc",
    "dataset": "misc",
    "software": "misc",
    "patent": "misc",
    "map": "misc",
    "motion_picture": "misc",
    "broadcast": "misc",
    "song": "misc",
    "graphic": "misc",
    "interview": "misc",
    "personal_communication": "misc",
    "legal_case": "misc",
    "legislation": "misc",
    "bill": "misc",
    "treaty": "misc",
    "document": "misc",
}

#: Where BibLaTeX has a type of its own for what BibTeX calls `misc`.
_BIBLATEX_TYPES = {
    "thesis": "thesis",
    "report": "report",
    "webpage": "online",
    "post": "online",
    "post-weblog": "online",
    "dataset": "dataset",
    "software": "software",
    "patent": "patent",
    "motion_picture": "movie",
    "broadcast": "video",
    "song": "audio",
    "manuscript": "unpublished",
}

#: CSL type to RIS reference type.
_RIS_TYPES = {
    "article-journal": "JOUR",
    "article-magazine": "MGZN",
    "article-newspaper": "NEWS",
    "article": "JOUR",
    "book": "BOOK",
    "chapter": "CHAP",
    "entry": "CHAP",
    "entry-dictionary": "DICT",
    "entry-encyclopedia": "ENCYC",
    "paper-conference": "CONF",
    "manuscript": "MANSCPT",
    "report": "RPRT",
    "thesis": "THES",
    "webpage": "ELEC",
    "post": "ELEC",
    "post-weblog": "BLOG",
    "speech": "SOUND",
    "dataset": "DATA",
    "software": "COMP",
    "patent": "PAT",
    "map": "MAP",
    "motion_picture": "MPCT",
    "broadcast": "MPCT",
    "song": "MUSIC",
    "graphic": "ART",
    "interview": "UNPB",
    "personal_communication": "PCOMM",
    "legal_case": "CASE",
    "legislation": "STAT",
    "bill": "BILL",
    "treaty": "STAT",
    "document": "GEN",
}

#: CSL name variables worth carrying, and the BibTeX field each becomes.
_BIBTEX_NAMES = {
    "author": "author",
    "editor": "editor",
    "translator": "translator",
    "container-author": "bookauthor",
}

#: Words a generated citation key skips when reaching for a title word.
_STOPWORDS = frozenset({"a", "an", "the", "on", "of", "in", "and", "or", "for", "to"})

#: What may appear in a citation key. BibTeX itself is stricter than most
#: readers, so this stays conservative.
_KEY_CHARACTERS = re.compile(r"[^A-Za-z0-9]+")


def _ascii(value: str) -> str:
    """Return ``value`` with accents folded away, for use in a citation key."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _year(csl: dict[str, Any]) -> str:
    issued = csl.get("issued") or {}
    parts = issued.get("date-parts") or [[]]
    return str(parts[0][0]) if parts[0] else ""


def _month(csl: dict[str, Any]) -> str:
    parts = (csl.get("issued") or {}).get("date-parts") or [[]]
    return str(parts[0][1]) if len(parts[0]) > 1 else ""


def _names(csl: dict[str, Any], variable: str) -> list[str]:
    """Return one CSL name variable as ``Family, Given`` strings."""
    names = []
    for name in csl.get(variable) or []:
        family = (name.get("family") or "").strip()
        given = (name.get("given") or "").strip()
        if family and given:
            names.append(f"{family}, {given}")
        elif family or given:
            names.append(family or given)
    return names


def _suffix(index: int) -> str:
    """Return the ``index``-th disambiguating letter: ``a`` … ``z``, then ``aa``.

    Counting in letters rather than in code points. The obvious ``chr(ord("a")
    + index)`` is right for the first twenty-six and writes punctuation, control
    characters and eventually whole other alphabets after that -- and a
    citation key is something a person types.
    """
    letters = ""
    while True:
        index, remainder = divmod(index, 26)
        letters = chr(ord("a") + remainder) + letters
        if index == 0:
            return letters
        index -= 1


def citation_key(csl: dict[str, Any], taken: set[str]) -> str:
    """Return a citation key for an item, unique within one export.

    Built the way people write them by hand -- first author, year, first real
    word of the title -- because a key is something a person types into a
    document. Collisions within the export get a letter, and an item with
    nothing to build from falls back to its own key, which is unique by
    definition.
    """
    author = (csl.get("author") or csl.get("editor") or [{}])[0]
    surname = _KEY_CHARACTERS.sub("", _ascii(author.get("family") or "")).lower()

    words = _KEY_CHARACTERS.sub(" ", _ascii(str(csl.get("title") or ""))).lower().split()
    word = next((entry for entry in words if entry not in _STOPWORDS), "")

    # A key beginning with a digit is legal but trips up enough tools to be
    # worth avoiding, so a year never leads.
    order = (surname, _year(csl), word) if surname else (word, _year(csl))
    stem = "".join(part for part in order if part)
    if not stem:
        stem = str(csl.get("id", "")).rpartition("/")[2] or "item"

    candidate = stem
    index = 0
    while candidate in taken:
        candidate = f"{stem}{_suffix(index)}"
        index += 1
    taken.add(candidate)
    return candidate


def _bibtex_entry(
    csl: dict[str, Any], keywords: Sequence[str], taken: set[str], *, biblatex: bool
) -> dict[str, str]:
    csl_type = str(csl.get("type", "document"))
    entry_type = _BIBTEX_TYPES.get(csl_type, "misc")
    if biblatex:
        entry_type = _BIBLATEX_TYPES.get(csl_type, entry_type)

    entry: dict[str, str] = {"ENTRYTYPE": entry_type, "ID": citation_key(csl, taken)}

    for variable, field in _BIBTEX_NAMES.items():
        if names := _names(csl, variable):
            entry[field] = " and ".join(names)

    container = str(csl.get("container-title") or "")
    if container:
        # A journal is a journal; anything a chapter or a paper sits inside is
        # a book as far as BibTeX is concerned.
        entry["journal" if entry_type == "article" else "booktitle"] = container

    simple = {
        "title": "title",
        "publisher": "publisher",
        "publisher-place": "address",
        "volume": "volume",
        "issue": "number",
        "number": "number",
        "edition": "edition",
        "collection-title": "series",
        "DOI": "doi",
        "ISBN": "isbn",
        "ISSN": "issn",
        "URL": "url",
        "abstract": "abstract",
        "note": "note",
        "genre": "type",
        "number-of-pages": "pages",
        "language": "language",
    }
    for variable, field in simple.items():
        if value := csl.get(variable):
            entry.setdefault(field, str(value))

    if page := csl.get("page"):
        # BibTeX's range is an en dash written as two hyphens.
        entry["pages"] = re.sub(r"\s*-+\s*", "--", str(page))

    if year := _year(csl):
        entry["year"] = year
    if month := _month(csl):
        entry["month"] = month
    if keywords:
        entry["keywords"] = ", ".join(keywords)

    return entry


def bibtex(
    items: Sequence[dict[str, Any]],
    *,
    keywords: Sequence[Sequence[str]] | None = None,
    biblatex: bool = False,
    taken: set[str] | None = None,
) -> str:
    """Return items as a BibTeX or BibLaTeX file.

    Args:
        items: CSL JSON objects, as :func:`altero.cite.csl_item` produces.
        keywords: Tags for each item, in the same order. Tags are not part of
            CSL, so they are carried alongside rather than folded into it.
        biblatex: Use BibLaTeX's larger set of entry types.
        taken: Citation keys already spoken for, added to as more are made. A
            file written in several passes -- an export longer than one batch --
            passes one set through all of them, because a citation key is unique
            within a file and not within a call.
    """
    from bibtexparser.bibdatabase import BibDatabase
    from bibtexparser.bwriter import BibTexWriter

    taken = set() if taken is None else taken
    database = BibDatabase()
    database.entries = [
        _bibtex_entry(csl, (keywords or [])[index] if keywords else (), taken, biblatex=biblatex)
        for index, csl in enumerate(items)
    ]

    writer = BibTexWriter()
    writer.indent = "  "
    # Written in the order asked for, which is the order the request sorted by.
    # bibtexparser types this as a tuple of field names; None is its own
    # documented way of saying "do not reorder".
    writer.order_entries_by = None  # ty: ignore[invalid-assignment]
    return str(writer.write(database))


def _ris_entry(csl: dict[str, Any], keywords: Sequence[str]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type_of_reference": _RIS_TYPES.get(str(csl.get("type", "document")), "GEN"),
    }

    if title := csl.get("title"):
        entry["title"] = str(title)
    for variable, field in (
        ("author", "authors"),
        ("editor", "secondary_authors"),
        ("translator", "tertiary_authors"),
    ):
        if names := _names(csl, variable):
            entry[field] = names

    if container := csl.get("container-title"):
        entry["journal_name"] = str(container)
    if year := _year(csl):
        entry["year"] = year

    simple = {
        "volume": "volume",
        "issue": "number",
        "publisher": "publisher",
        "publisher-place": "place_published",
        "DOI": "doi",
        "ISBN": "issn",
        "ISSN": "issn",
        "abstract": "abstract",
        "edition": "edition",
        "language": "language",
        "note": "notes_abstract",
    }
    for variable, field in simple.items():
        if value := csl.get(variable):
            entry.setdefault(field, str(value))

    if url := csl.get("URL"):
        # RIS calls the tag UR and rispy calls it `urls`, plural and a list.
        entry["urls"] = [str(url)]

    if page := csl.get("page"):
        first, _, last = str(page).partition("-")
        entry["start_page"] = first.strip()
        if last.strip():
            entry["end_page"] = last.strip()

    if keywords:
        entry["keywords"] = list(keywords)

    return entry


def ris(items: Sequence[dict[str, Any]], *, keywords: Sequence[Sequence[str]] | None = None) -> str:
    """Return items as an RIS file.

    Args:
        items: CSL JSON objects.
        keywords: Tags for each item, in the same order.
    """
    import rispy
    from rispy.writer import RisWriter

    class _Writer(RisWriter):
        """RIS without rispy's record numbers, which are not part of the format."""

        def set_header(self, count: int) -> str:
            return ""

    entries = [
        _ris_entry(csl, (keywords or [])[index] if keywords else ())
        for index, csl in enumerate(items)
    ]
    return str(rispy.dumps(entries, implementation=_Writer))
