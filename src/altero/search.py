"""The Zotero search syntax used by the ``itemType`` and ``tag`` parameters.

A single parameter value holds alternatives separated by ``||`` (OR), each of
which may be negated by a leading ``-`` (NOT). A leading hyphen is escaped as
``\\-``. Conjunction is expressed by repeating the parameter, so ``tag=foo&tag=bar``
matches items carrying both tags.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Separator between alternatives within one parameter value.
OR_SEPARATOR = "||"


@dataclass(frozen=True, slots=True)
class SearchTerm:
    """A single value, optionally negated."""

    value: str
    negated: bool = False


@dataclass(frozen=True, slots=True)
class SearchExpression:
    """The alternatives of one parameter value, combined with OR."""

    terms: tuple[SearchTerm, ...]

    def __bool__(self) -> bool:
        return bool(self.terms)


def _parse_term(raw: str) -> SearchTerm | None:
    """Parse one alternative. Returns ``None`` for a blank value."""
    value = raw.strip()
    if not value:
        return None
    if value.startswith(r"\-"):
        # An escaped hyphen is part of the value rather than an operator.
        return SearchTerm(value[1:], negated=False)
    if value.startswith("-"):
        return SearchTerm(value[1:], negated=True)
    return SearchTerm(value, negated=False)


def parse_expression(raw: str) -> SearchExpression:
    """Parse a single parameter value into its OR-ed alternatives."""
    terms = (_parse_term(part) for part in raw.split(OR_SEPARATOR))
    return SearchExpression(tuple(term for term in terms if term is not None))


def parse_expressions(raws: Sequence[str] | Iterable[str]) -> tuple[SearchExpression, ...]:
    """Parse repeated parameter values, which are combined with AND."""
    expressions = (parse_expression(raw) for raw in raws)
    return tuple(expression for expression in expressions if expression)
