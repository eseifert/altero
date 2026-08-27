"""The languages the server offers, against the catalogues that exist.

The server decides which languages an account may be set to; the interface
holds the messages. Nothing else connects the two, so a language offered with
no catalogue would be accepted, stored, and then render as English -- and one
translated but not offered would be unreachable.
"""

import re
from pathlib import Path

import pytest

from altero.errors import InvalidInputError
from altero.services.locales import (
    DEFAULT_LANGUAGE,
    DEFAULT_VARIANTS,
    LANGUAGES,
    VARIANT_SUBTAGS,
    normalise_language,
    normalise_time_zone,
)

#: Where the interface keeps its message catalogues.
CATALOGUES = Path(__file__).resolve().parent.parent / "web" / "src" / "locales"

#: The browser's copy of the same tables, which it needs before it has asked the
#: server anything.
I18N = Path(__file__).resolve().parent.parent / "web" / "src" / "i18n.ts"


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
        assert LANGUAGES["pl"] == "Polski"
        assert LANGUAGES["ru"] == "Русский"
        assert LANGUAGES["zh-CN"] == "简体中文"

    def test_a_split_language_names_its_territory_in_itself_too(self) -> None:
        """The two Chinese catalogues are told apart by script and the rest by
        territory, which is how each names itself where it is read."""
        assert LANGUAGES["zh-TW"] == "繁體中文"
        assert LANGUAGES["pt-BR"] == "Português (Brasil)"
        assert LANGUAGES["pt-PT"] == "Português (Portugal)"

    def test_none_is_named_in_english_but_english(self) -> None:
        assert [tag for tag, name in LANGUAGES.items() if name.startswith("English")] == [
            "en-US",
            "en-GB",
        ]

    def test_every_variant_a_tag_can_resolve_to_is_offered(self) -> None:
        """A table that sent `en-AU` somewhere with no catalogue would store a
        language the interface then renders in English."""
        resolved = set(DEFAULT_VARIANTS.values())
        for variants in VARIANT_SUBTAGS.values():
            resolved |= set(variants.values())

        assert resolved <= set(LANGUAGES)

    def test_only_a_language_without_a_catalogue_of_its_own_has_variants(self) -> None:
        """`de` is carried once, so nothing should be deciding between German
        territories."""
        assert set(VARIANT_SUBTAGS) == set(DEFAULT_VARIANTS)
        assert not set(VARIANT_SUBTAGS) & set(LANGUAGES)


class TestTheBrowserAgreesAboutThem:
    """The tables in `i18n.ts`, against these.

    The browser resolves a tag before it has asked the server anything -- on the
    sign-in page there is no account to ask about -- so it carries the same two
    tables. Two copies that disagreed would render one language and store
    another.
    """

    @staticmethod
    def _table(name: str) -> dict[str, str]:
        source = I18N.read_text(encoding="utf-8")
        body = source[source.index(f"export const {name}") :]
        body = body[body.index("{") : body.index("\n}") + 2]
        return dict(re.findall(r"'?([A-Za-z-]+)'?:\s*'([a-zA-Z-]+)'", body))

    def test_the_default_variants_match(self) -> None:
        assert self._table("DEFAULT_VARIANTS") == DEFAULT_VARIANTS

    def test_the_variant_subtags_match(self) -> None:
        flattened = {
            subtag: tag for variants in VARIANT_SUBTAGS.values() for subtag, tag in variants.items()
        }

        assert self._table("VARIANT_SUBTAGS") == flattened


class TestNormalisingALanguage:
    def test_none_means_follow_the_browser(self) -> None:
        assert normalise_language(None) is None
        assert normalise_language("") is None

    def test_a_plain_tag_is_kept(self) -> None:
        assert normalise_language("fr") == "fr"

    @pytest.mark.parametrize("tag", ["de-AT", "de_AT", "DE-at", " de-AT "])
    def test_a_region_narrows_to_its_language(self, tag: str) -> None:
        """German is carried once, so the region reaches the shape of a date and
        nothing else, and the browser supplies that separately."""
        assert normalise_language(tag) == "de"

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ("pt-BR", "pt-BR"),
            ("pt_br", "pt-BR"),
            (" PT-pt ", "pt-PT"),
            ("en-GB", "en-GB"),
            ("zh-TW", "zh-TW"),
            ("zh-CN", "zh-CN"),
        ],
    )
    def test_a_region_that_changes_the_words_is_kept(self, tag: str, expected: str) -> None:
        assert normalise_language(tag) == expected

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [("zh-Hans", "zh-CN"), ("zh-Hans-CN", "zh-CN"), ("zh-Hant", "zh-TW")],
    )
    def test_a_script_picks_the_catalogue_written_in_it(self, tag: str, expected: str) -> None:
        assert normalise_language(tag) == expected

    @pytest.mark.parametrize(
        ("tag", "expected"), [("en", "en-US"), ("pt", "pt-BR"), ("zh", "zh-CN")]
    )
    def test_a_bare_language_goes_where_cldr_sends_it(self, tag: str, expected: str) -> None:
        assert normalise_language(tag) == expected

    @pytest.mark.parametrize(
        ("tag", "expected"),
        [("en-AU", "en-GB"), ("en-IE", "en-GB"), ("zh-HK", "zh-TW"), ("pt-MZ", "pt-PT")],
    )
    def test_a_territory_without_a_catalogue_reads_the_nearest(
        self, tag: str, expected: str
    ) -> None:
        assert normalise_language(tag) == expected

    def test_an_unlisted_territory_falls_back_to_the_default_variant(self) -> None:
        assert normalise_language("en-CA") == "en-US"

    def test_a_language_with_no_catalogue_is_refused(self) -> None:
        with pytest.raises(InvalidInputError, match="Unsupported language"):
            normalise_language("kl")

    def test_a_region_does_not_rescue_a_language_with_no_catalogue(self) -> None:
        with pytest.raises(InvalidInputError, match="Unsupported language"):
            normalise_language("kl-GL")


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
