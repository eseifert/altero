r"""The Zotero search syntax used by the ``itemType`` and ``tag`` parameters.

The rules follow ``Zotero_API::getSearchParamValues`` in the official dataserver
rather than the prose documentation, which describes them loosely:

- A leading ``-`` negates the **whole** parameter value, not an individual
  alternative. ``itemType=-book || journalArticle`` therefore excludes items of
  either type; it does not mean "not a book, or a journal article".
- Alternatives are separated by ``||`` **with whitespace on both sides**
  (``/\s+\|\|\s+/``). ``tag=a||b`` is a single tag literally named ``a||b``,
  which is why a tag containing a bare ``||`` still round-trips.
- Only the whole value is stripped, once, before parsing. Alternatives keep any
  inner spacing, so ``tag=foo bar || bar`` looks for ``foo bar`` and ``bar``.
- ``\-`` escapes a leading hyphen, yielding a value that starts with ``-``.

Repeating the parameter conjoins the expressions, so ``tag=foo&tag=bar`` matches
items carrying both.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Separator between alternatives. Whitespace on both sides is required.
OR_SEPARATOR = re.compile(r"\s+\|\|\s+")


@dataclass(frozen=True, slots=True)
class SearchExpression:
    """One parameter value: alternatives combined with OR, optionally negated.

    ``negated`` applies to the whole set of ``values``, matching the reference
    implementation.
    """

    values: tuple[str, ...]
    negated: bool = False

    def __bool__(self) -> bool:
        return bool(self.values)


def parse_expression(raw: str) -> SearchExpression:
    """Parse a single parameter value."""
    value = raw.strip()
    if not value:
        return SearchExpression(())

    negated = False
    if value.startswith("-"):
        negated = True
        value = value[1:]
    elif value.startswith("\\-"):
        # An escaped hyphen is part of the value rather than an operator.
        value = value[1:]

    return SearchExpression(tuple(OR_SEPARATOR.split(value)), negated=negated)


def parse_expressions(raws: Sequence[str] | Iterable[str]) -> tuple[SearchExpression, ...]:
    """Parse repeated parameter values, which are combined with AND."""
    expressions = (parse_expression(raw) for raw in raws)
    return tuple(expression for expression in expressions if expression)
