"""The languages the server offers, against the catalogues that exist.

The server decides which languages an account may be set to; the interface
holds the messages. Nothing else connects the two, so a language offered with
no catalogue would be accepted, stored, and then render as English -- and one
translated but not offered would be unreachable.
"""

from pathlib import Path

import pytest

from altero.errors import InvalidInputError
from altero.services.locales import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    normalise_language,
    normalise_time_zone,
)

#: Where the interface keeps its message catalogues.
CATALOGUES = Path(__file__).resolve().parent.parent / "web" / "src" / "locales"


def catalogue_tags() -> set[str]:
    return {path.stem for path in CATALOGUES.glob("*.ts") if not path.name.endswith(".spec.ts")}


class TestTheOfferedLanguages:
    def test_every_language_offered_has_a_catalogue(self) -> None:
        assert set(LANGUAGES) <= catalogue_tags()

    def test_every_catalogue_is_offered(self) -> None:
        """A translation nobody can select is work that reaches no one."""
        assert catalogue_tags() <= set(LANGUAGES)

    def test_the_default_is_one_of_them(self) -> None:
        assert DEFAULT_LANGUAGE in LANGUAGES

    def test_each_is_named_in_itself(self) -> None:
        """A language list in one language is only useful to people who read it."""
        assert LANGUAGES["de"] == "Deutsch"
        assert LANGUAGES["ja"] == "日本語"


class TestNormalisingALanguage:
    def test_none_means_follow_the_browser(self) -> None:
        assert normalise_language(None) is None
        assert normalise_language("") is None

    def test_a_plain_tag_is_kept(self) -> None:
        assert normalise_language("fr") == "fr"

    @pytest.mark.parametrize("tag", ["pt-BR", "pt_BR", "PT-br", " pt-BR "])
    def test_a_region_narrows_to_its_language(self, tag: str) -> None:
        assert normalise_language(tag) == "pt"

    def test_a_language_with_no_catalogue_is_refused(self) -> None:
        with pytest.raises(InvalidInputError, match="Unsupported language"):
            normalise_language("kl")


class TestNormalisingATimeZone:
    def test_none_means_follow_the_browser(self) -> None:
        assert normalise_time_zone(None) is None
        assert normalise_time_zone("") is None

    def test_an_iana_name_is_kept(self) -> None:
        assert normalise_time_zone("Europe/Berlin") == "Europe/Berlin"

    def test_utc_is_a_zone(self) -> None:
        assert normalise_time_zone("UTC") == "UTC"

    @pytest.mark.parametrize("value", ["Mars/Olympus", "+02:00", "CEST", "Europe/Berlin/../.."])
    def test_anything_else_is_refused(self, value: str) -> None:
        with pytest.raises(InvalidInputError, match="Unknown time zone"):
            normalise_time_zone(value)
