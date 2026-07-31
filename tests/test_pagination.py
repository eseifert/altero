"""Tests for pagination and the Link header."""

import pytest

from altero.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    UNLIMITED,
    build_page_links,
    clamp_limit,
    format_link_header,
)


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        (None, DEFAULT_LIMIT),
        (1, 1),
        (25, 25),
        (100, 100),
        (101, MAX_LIMIT),
        (1000, MAX_LIMIT),
        # Zero or less falls back to the default rather than to a single
        # result, matching Zotero_API::parseQueryParams.
        (0, DEFAULT_LIMIT),
        (-5, DEFAULT_LIMIT),
    ],
)
def test_limit_is_clamped_to_the_documented_range(supplied: int | None, expected: int) -> None:
    assert clamp_limit(supplied) == expected


def test_an_unlimited_maximum_does_not_clamp() -> None:
    assert clamp_limit(5000, maximum=UNLIMITED, default=UNLIMITED) == 5000


def test_an_unlimited_default_applies_when_nothing_is_supplied() -> None:
    assert clamp_limit(None, maximum=UNLIMITED, default=UNLIMITED) == UNLIMITED


def test_an_explicit_limit_still_wins_over_an_unlimited_default() -> None:
    assert clamp_limit(10, maximum=UNLIMITED, default=UNLIMITED) == 10


def test_an_unlimited_page_has_no_links() -> None:
    links = build_page_links("http://localhost/x", [], start=0, limit=UNLIMITED, total=500)

    assert links == {}


def test_the_first_page_offers_only_forward_links() -> None:
    links = build_page_links("http://localhost/users/1/items", [], start=0, limit=25, total=100)

    assert set(links) == {"next", "last"}
    assert links["next"].endswith("?limit=25&start=25")
    assert links["last"].endswith("?limit=25&start=75")


def test_a_middle_page_offers_links_in_both_directions() -> None:
    links = build_page_links("http://localhost/users/1/items", [], start=25, limit=25, total=100)

    assert list(links) == ["first", "prev", "next", "last"]
    # A zero start is left out entirely, as upstream writes it.
    assert links["first"].endswith("?limit=25")
    assert links["prev"].endswith("?limit=25")
    assert links["next"].endswith("?limit=25&start=50")
    assert links["last"].endswith("?limit=25&start=75")


def test_the_last_page_offers_only_backward_links() -> None:
    links = build_page_links("http://localhost/users/1/items", [], start=75, limit=25, total=100)

    assert set(links) == {"first", "prev"}
    assert links["prev"].endswith("?limit=25&start=50")


def test_a_single_page_of_results_has_no_links() -> None:
    assert build_page_links("http://localhost/x", [], start=0, limit=25, total=10) == {}


def test_no_results_has_no_links() -> None:
    assert build_page_links("http://localhost/x", [], start=0, limit=25, total=0) == {}


def test_a_partial_final_page_is_addressed_by_its_own_start() -> None:
    links = build_page_links("http://localhost/x", [], start=0, limit=25, total=101)

    assert links["last"].endswith("start=100")


def test_an_exactly_full_last_page_is_not_overshot() -> None:
    links = build_page_links("http://localhost/x", [], start=0, limit=25, total=50)

    assert links["last"].endswith("start=25")
    assert "next" in links


def test_prev_does_not_go_below_zero() -> None:
    links = build_page_links("http://localhost/x", [], start=10, limit=25, total=100)

    assert links["prev"].endswith("?limit=25")


def test_other_query_parameters_are_preserved() -> None:
    links = build_page_links(
        "http://localhost/users/1/items",
        [("itemType", "book"), ("sort", "title")],
        start=0,
        limit=25,
        total=100,
    )

    assert "itemType=book" in links["next"]
    assert "sort=title" in links["next"]


def test_repeated_query_parameters_are_preserved() -> None:
    links = build_page_links(
        "http://localhost/users/1/items",
        [("tag", "foo"), ("tag", "bar")],
        start=0,
        limit=25,
        total=100,
    )

    assert links["next"].count("tag=") == 2


def test_supplied_start_and_limit_are_replaced_not_duplicated() -> None:
    links = build_page_links(
        "http://localhost/users/1/items",
        [("start", "0"), ("limit", "25")],
        start=0,
        limit=25,
        total=100,
    )

    assert links["next"].count("start=") == 1
    assert links["next"].count("limit=") == 1
    assert links["next"].endswith("start=25")


def test_query_parameters_are_url_encoded() -> None:
    links = build_page_links(
        "http://localhost/users/1/items",
        [("q", "foo bar")],
        start=0,
        limit=25,
        total=100,
    )

    assert "q=foo+bar" in links["next"] or "q=foo%20bar" in links["next"]


def test_link_header_formatting() -> None:
    header = format_link_header({"next": "http://localhost/a", "last": "http://localhost/b"})

    assert header == '<http://localhost/a>; rel="next", <http://localhost/b>; rel="last"'


def test_link_header_is_empty_without_links() -> None:
    assert format_link_header({}) == ""
