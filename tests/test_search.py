"""Tests for the Zotero search syntax.

The examples in the documentation are:

    itemType=book
    itemType=book || journalArticle   (OR)
    itemType=-attachment              (NOT)
    tag=foo
    tag=foo bar                       (tag with space)
    tag=foo&tag=bar                   (AND)
    tag=foo bar || bar                (OR)
    tag=-foo                          (NOT)
    tag=\\-foo                         (literal first-character hyphen)
"""

from altero.search import SearchTerm, parse_expression, parse_expressions


def test_a_single_value_becomes_one_term() -> None:
    assert parse_expression("book").terms == (SearchTerm("book", negated=False),)


def test_double_pipe_separates_alternatives() -> None:
    expression = parse_expression("book || journalArticle")

    assert expression.terms == (
        SearchTerm("book", negated=False),
        SearchTerm("journalArticle", negated=False),
    )


def test_alternatives_do_not_require_surrounding_whitespace() -> None:
    assert parse_expression("book||journalArticle") == parse_expression("book || journalArticle")


def test_a_leading_hyphen_negates_a_term() -> None:
    assert parse_expression("-attachment").terms == (SearchTerm("attachment", negated=True),)


def test_negation_applies_per_term() -> None:
    expression = parse_expression("foo || -bar")

    assert expression.terms == (
        SearchTerm("foo", negated=False),
        SearchTerm("bar", negated=True),
    )


def test_a_backslash_escapes_a_literal_leading_hyphen() -> None:
    assert parse_expression(r"\-foo").terms == (SearchTerm("-foo", negated=False),)


def test_only_a_leading_hyphen_is_special() -> None:
    assert parse_expression("foo-bar").terms == (SearchTerm("foo-bar", negated=False),)


def test_spaces_inside_a_value_are_preserved() -> None:
    assert parse_expression("foo bar").terms == (SearchTerm("foo bar", negated=False),)


def test_spaces_are_preserved_within_alternatives() -> None:
    expression = parse_expression("foo bar || bar")

    assert expression.terms == (
        SearchTerm("foo bar", negated=False),
        SearchTerm("bar", negated=False),
    )


def test_an_empty_value_yields_no_terms() -> None:
    expression = parse_expression("")

    assert expression.terms == ()
    assert not expression


def test_blank_alternatives_are_dropped() -> None:
    assert parse_expression("foo || ").terms == (SearchTerm("foo", negated=False),)


def test_repeated_parameters_are_combined_with_and() -> None:
    expressions = parse_expressions(["foo", "bar"])

    assert len(expressions) == 2
    assert expressions[0].terms == (SearchTerm("foo", negated=False),)
    assert expressions[1].terms == (SearchTerm("bar", negated=False),)


def test_empty_parameters_are_dropped_when_combining() -> None:
    assert parse_expressions(["foo", ""]) == parse_expressions(["foo"])


def test_no_parameters_yields_no_expressions() -> None:
    assert parse_expressions([]) == ()
