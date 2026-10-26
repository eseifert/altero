"""Changing an item's type the way the desktop's item pane does.

Each case is a line of ``Zotero.Item.prototype.setType`` or of the warning in
``itemBox.js`` that comes before it.
"""

import pytest

from altero.errors import InvalidInputError
from altero.itemschema import get_schema
from altero.itemschema.typechange import TypeChange, change_type

AUTHOR = {"creatorType": "author", "firstName": "Harold", "lastName": "Abelson"}
EDITOR = {"creatorType": "editor", "firstName": "Ed", "lastName": "Itor"}


def change(
    old: str, new: str, values: dict[str, str], creators: tuple[dict[str, str], ...] = ()
) -> TypeChange:
    return change_type(get_schema(), old, new, values, list(creators))


def test_a_field_both_types_have_stays() -> None:
    result = change("book", "report", {"title": "SICP", "date": "1985"})

    assert result.fields == {"title": "SICP", "date": "1985"}
    assert result.lost == []


def test_a_field_moves_to_its_counterpart() -> None:
    """A book's publisher is a report's institution: the same base field."""
    result = change("book", "report", {"publisher": "MIT Press"})

    assert result.fields == {"institution": "MIT Press"}
    assert result.lost == []


def test_a_field_with_no_counterpart_is_lost() -> None:
    result = change("book", "film", {"title": "SICP", "edition": "2", "numPages": "657"})

    assert result.fields == {"title": "SICP"}
    assert result.lost == ["edition", "numPages"]


def test_the_lost_fields_come_in_the_old_type_s_order() -> None:
    result = change("book", "film", {"numPages": "657", "edition": "2"})

    assert result.lost == ["edition", "numPages"]


def test_an_empty_field_is_neither_kept_nor_lost() -> None:
    result = change("book", "film", {"edition": "", "title": ""})

    assert result.fields == {}
    assert result.lost == []


def test_a_book_s_title_becomes_a_section_s_book_title() -> None:
    result = change("book", "bookSection", {"title": "SICP", "shortTitle": "SICP"})

    assert result.fields == {"bookTitle": "SICP"}
    # The item pane warns about the short title, which goes with it.
    assert result.lost == ["shortTitle"]


def test_a_section_without_a_title_gives_its_book_title_to_the_book() -> None:
    result = change("bookSection", "book", {"bookTitle": "SICP", "shortTitle": "S"})

    assert result.fields == {"title": "SICP"}
    assert result.lost == ["shortTitle"]


def test_a_section_with_a_title_keeps_it_and_loses_the_book_title() -> None:
    result = change("bookSection", "book", {"title": "Chapter", "bookTitle": "SICP"})

    assert result.fields == {"title": "Chapter"}
    assert result.lost == ["bookTitle"]


def test_the_primary_creator_takes_the_new_primary_role() -> None:
    """Upstream's server makes every misfit a contributor; the desktop does not."""
    result = change("book", "film", {}, (AUTHOR, EDITOR))

    assert [creator["creatorType"] for creator in result.creators] == ["director", "contributor"]
    assert result.creators[0]["lastName"] == "Abelson"


def test_a_role_the_new_type_has_is_kept() -> None:
    result = change("book", "journalArticle", {}, (AUTHOR, EDITOR))

    assert [creator["creatorType"] for creator in result.creators] == ["author", "editor"]


@pytest.mark.parametrize(("old", "new"), [("book", "note"), ("attachment", "book")])
def test_notes_attachments_and_annotations_keep_their_type(old: str, new: str) -> None:
    with pytest.raises(InvalidInputError):
        change(old, new, {})


def test_an_unknown_type_is_refused() -> None:
    with pytest.raises(InvalidInputError):
        change("book", "nosuch", {})
