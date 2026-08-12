"""Turning the free-text dates Zotero stores into CSL date variables.

A Zotero date field holds whatever the person or the translator typed:
``2019-04-03``, ``April 2019``, ``Spring 1998``, ``n.d.``. CSL wants
``date-parts`` with only the components that are actually known, so the job here
is as much about deciding how much of a date is present as about reading it.

The reference implementation calls its own ``Zotero_Date::strToDate``; this uses
:mod:`dateparser`, which reports the granularity it managed to reach and
recognises the same shapes in a good many languages. A date it cannot read at
all becomes a CSL ``literal``, which is what upstream does with a date carrying
no year.
"""

import re
from functools import lru_cache
from typing import Any

#: A complete or partial ISO date, which is the common case and is answered
#: without waking the general parser.
_ISO = re.compile(r"^\s*(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?\s*$")

#: Any four-digit year, used as the last resort before giving up on a date.
_YEAR = re.compile(r"\b(\d{4})\b")

#: Settings for :mod:`dateparser`. Two of them matter:
#:
#: Relative parsing is off, because a publication date is never "two days ago"
#: and leaving it on lets stray words resolve against today.
#:
#: A year is required, because without it the parser fills in the missing parts
#: from today: ``n.d.`` -- which is precisely a statement that there is no date
#: -- comes back as this morning. A date with no year belongs in a CSL
#: ``literal`` instead.
_SETTINGS = {
    "PARSERS": ["custom-formats", "absolute-time"],
    "PREFER_DAY_OF_MONTH": "first",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "REQUIRE_PARTS": ["year"],
}


@lru_cache(maxsize=1)
def _parser() -> Any:
    """Return the shared parser, built on first use.

    Importing :mod:`dateparser` costs the better part of a second and loads a
    pile of language data, so a server that never renders a citation never pays
    for it.
    """
    from dateparser.date import DateDataParser

    return DateDataParser(settings=_SETTINGS)


@lru_cache(maxsize=4096)
def date_parts(raw: str) -> tuple[int, ...] | None:
    """Return the year, month and day known for ``raw``, as far as they go.

    Returns:
        A tuple of one to three integers, or ``None`` when no date could be
        read. Months are 1-indexed, as CSL expects them.
    """
    value = (raw or "").strip()
    if not value:
        return None

    if match := _ISO.match(value):
        year, month, day = match.groups()
        return tuple(int(part) for part in (year, month, day) if part)

    try:
        parsed = _parser().get_date_data(value)
    except ValueError, TypeError, RecursionError, OverflowError:
        # dateparser raises on some malformed input rather than reporting it as
        # unparseable, and a bad date in one field must not fail the request.
        return None

    date = parsed["date_obj"]
    if date is None:
        return None

    period = parsed["period"]
    if period == "year":
        return (date.year,)
    if period == "month":
        return (date.year, date.month)
    return (date.year, date.month, date.day)


def iso_date(raw: str) -> str:
    """Return a stored date as far as it is known, in ISO order.

    ``Zotero.Date.strToISO``, which the OpenURL context object and several
    export formats write dates with: a year alone stays a year, and a date that
    cannot be read at all is empty rather than guessed at.
    """
    parts = date_parts(raw)
    if not parts:
        return ""
    return "-".join(f"{part:02d}" if index else f"{part:04d}" for index, part in enumerate(parts))


def csl_date(raw: str) -> dict[str, Any] | None:
    """Return the CSL date variable for a stored date field.

    A date with no readable year is passed through as a ``literal`` rather than
    dropped, so ``forthcoming`` still reaches the citation processor. A year
    with unparseable text beside it -- ``Spring 2019`` -- keeps that text as the
    CSL ``season``, which is where upstream puts it too.
    """
    value = (raw or "").strip()
    if not value:
        return None

    if parts := date_parts(value):
        return {"date-parts": [list(parts)]}

    if match := _YEAR.search(value):
        date: dict[str, Any] = {"date-parts": [[int(match.group(1))]]}
        remainder = (value[: match.start()] + " " + value[match.end() :]).strip(" ,.-/")
        # Only words are worth keeping: the leftovers of a range or a stray
        # separator say nothing a style could render.
        if re.search(r"[^\W\d_]", remainder):
            date["season"] = remainder
        return date

    return {"literal": value}
