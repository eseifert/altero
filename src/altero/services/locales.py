"""The languages the interface offers, and the time zones it accepts.

Kept on the server rather than only in the browser because both are account
settings: somebody who signs in from a borrowed machine should find their own
library in their own language, not the machine's.

Neither has a default stored. A null language or time zone means "follow the
browser", which is a setting in its own right — storing whatever the browser
asked for on the day the account was made would freeze it against the person who
moves between machines set up differently.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from altero.errors import InvalidInputError

#: Interface languages, by BCP 47 tag, with the name each is called in itself.
#: A tag here must have a catalogue in `web/src/locales`; the two are checked
#: against each other by `tests/test_locales.py`.
#:
#: Keyed by language alone, never by region or script, because that is the
#: granularity the catalogues have -- which is why Chinese names itself as the
#: script it is written in rather than as `中文`. Somebody arriving with
#: `zh-TW` gets Simplified words; their dates stay Taiwanese, formatting being
#: the browser's tag rather than this one.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "pt": "Português",
    "it": "Italiano",
    "nl": "Nederlands",
    "da": "Dansk",
    "pl": "Polski",
    "ru": "Русский",
    "ja": "日本語",
    "zh": "简体中文",
}

#: The language used when a request carries no usable preference at all.
DEFAULT_LANGUAGE = "en"


def normalise_language(value: str | None) -> str | None:
    """Return a stored language tag, or ``None`` for "follow the browser".

    A tag with a region -- ``de-AT``, ``pt-BR`` -- is accepted and narrowed to
    the language, because that is the granularity the catalogues have. The
    region still matters for formatting dates, and the browser keeps supplying
    that separately.

    Raises:
        InvalidInputError: The tag names a language with no catalogue.
    """
    if value is None or value == "":
        return None

    tag = value.strip().replace("_", "-")
    language = tag.partition("-")[0].lower()
    if language not in LANGUAGES:
        raise InvalidInputError(f"Unsupported language '{value}'")
    return language


def normalise_time_zone(value: str | None) -> str | None:
    """Return a stored IANA time zone, or ``None`` for "follow the browser".

    Checked against the zone database this server has rather than a list of our
    own, so a zone renamed or added upstream needs no change here.

    Raises:
        InvalidInputError: The name is not a zone this system knows.
    """
    if value is None or value == "":
        return None

    name = value.strip()
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError, KeyError:
        raise InvalidInputError(f"Unknown time zone '{name}'") from None

    # `ZoneInfo` accepts a path-like key that resolves to a file; the listing is
    # what the browser and the settings screen agree on.
    if name not in available_timezones():
        raise InvalidInputError(f"Unknown time zone '{name}'")
    return name
