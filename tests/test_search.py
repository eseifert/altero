r"""The Zotero search syntax.

Behaviour follows ``Zotero_API::getSearchParamValues`` in the official
dataserver, which differs from the prose documentation in two ways that matter:
negation applies to the whole parameter value rather than to one alternative,
and ``||`` only separates alternatives when it has whitespace on both sides.
"""

from altero.search import (
    SearchExpression,
    parse_expression,
    parse_expressions,
    parse_search_string,
)


def test_a_single_value_becomes_one_alternative() -> None:
    assert parse_expression("book") == SearchExpression(("book",), negated=False)


def test_double_pipe_separates_alternatives() -> None:
    assert parse_expression("book || journalArticle").values == ("book", "journalArticle")


def test_the_separator_requires_surrounding_whitespace() -> None:
    # The reference implementation splits on /\s+\|\|\s+/, so a bare `||` is
    # part of the value. A tag literally named `a||b` therefore round-trips.
    assert parse_expression("book||journalArticle").values == ("book||journalArticle",)


def test_a_one_sided_separator_does_not_split() -> None:
    assert parse_expression("book ||journalArticle").values == ("book ||journalArticle",)


def test_extra_whitespace_around_the_separator_is_consumed() -> None:
    assert parse_expression("book   ||   journalArticle").values == (
        "book",
        "journalArticle",
    )


def test_a_leading_hyphen_negates_the_whole_expression() -> None:
    assert parse_expression("-attachment") == SearchExpression(("attachment",), negated=True)


def test_negation_covers_every_alternative() -> None:
    # This excludes items of either type; it does not mean
    # "not a book, or a journal article".
    expression = parse_expression("-book || journalArticle")

    assert expression.negated
    assert expression.values == ("book", "journalArticle")


def test_a_backslash_escapes_a_literal_leading_hyphen() -> None:
    assert parse_expression(r"\-foo") == SearchExpression(("-foo",), negated=False)


def test_only_a_leading_hyphen_is_special() -> None:
    assert parse_expression("foo-bar") == SearchExpression(("foo-bar",), negated=False)


def test_spaces_inside_a_value_are_preserved() -> None:
    assert parse_expression("foo bar").values == ("foo bar",)


def test_spaces_are_preserved_within_alternatives() -> None:
    assert parse_expression("foo bar || bar").values == ("foo bar", "bar")


def test_surrounding_whitespace_is_stripped_once() -> None:
    assert parse_expression("  book  ").values == ("book",)


def test_an_empty_value_yields_nothing() -> None:
    expression = parse_expression("")

    assert expression.values == ()
    assert not expression


def test_a_whitespace_only_value_yields_nothing() -> None:
    assert not parse_expression("   ")


def test_repeated_parameters_are_combined_with_and() -> None:
    expressions = parse_expressions(["foo", "bar"])

    assert len(expressions) == 2
    assert expressions[0].values == ("foo",)
    assert expressions[1].values == ("bar",)


def test_empty_parameters_are_dropped_when_combining() -> None:
    assert parse_expressions(["foo", ""]) == parse_expressions(["foo"])


def test_no_parameters_yields_no_expressions() -> None:
    assert parse_expressions([]) == ()


class TestSplittingTheQuickSearch:
    """``q``, which follows ``Zotero_Utilities::parseSearchString``.

    The parts are AND-ed by the caller, so how the string divides decides
    whether a two-word query wants a phrase or two separate matches.
    """

    def test_a_single_word_is_one_part(self) -> None:
        assert parse_search_string("Ishmael") == ("Ishmael",)

    def test_words_are_separated(self) -> None:
        assert parse_search_string("Ishmael Pequod") == ("Ishmael", "Pequod")

    def test_runs_of_whitespace_collapse(self) -> None:
        assert parse_search_string("  Ishmael \t Pequod\n") == ("Ishmael", "Pequod")

    def test_a_quoted_phrase_survives_as_one_part(self) -> None:
        assert parse_search_string('"call me Ishmael"') == ("call me Ishmael",)

    def test_a_phrase_can_sit_beside_a_word(self) -> None:
        assert parse_search_string('whale "call me"') == ("whale", "call me")

    def test_boundary_single_quotes_are_stripped_without_grouping(self) -> None:
        # The reference implementation splits on a single quote only where it
        # touches whitespace or an end of the string, so it never groups.
        assert parse_search_string("'call me'") == ("call", "me")

    def test_an_inner_apostrophe_is_kept(self) -> None:
        assert parse_search_string("don't") == ("don't",)

    def test_an_empty_query_yields_no_parts(self) -> None:
        assert parse_search_string("") == ()

    def test_a_bare_zero_is_dropped(self) -> None:
        # `if (!$part) continue` in PHP drops "0" along with the empty string,
        # so `q=0` leaves no clause and matches everything rather than nothing.
        assert parse_search_string("0") == ()

    def test_a_zero_among_words_is_dropped(self) -> None:
        assert parse_search_string("volume 0 whale") == ("volume", "whale")

    def test_a_quoted_zero_is_kept(self) -> None:
        # The token is tested before its quotes come off, and `"0"` is truthy.
        assert parse_search_string('"0"') == ("0",)

    def test_a_zero_that_is_part_of_a_word_is_kept(self) -> None:
        assert parse_search_string("h2o 007") == ("h2o", "007")
