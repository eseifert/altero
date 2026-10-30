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
#: Keyed by language alone, except where a territory changes the words rather
#: than only the dates. Three do, and they are the three Zotero itself splits:
#: English, Portuguese and Chinese. A British reader empties the Bin and not the
#: Trash, a Brazilian saves a ficheiro as an arquivo, and Simplified and
#: Traditional Chinese do not share a script. Everywhere else the region reaches
#: dates and nothing else, and `de-AT` is German here.
#:
#: The default variant of each comes first.
LANGUAGES: dict[str, str] = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "de": "Deutsch",
    "fr": "Français",
    "br": "Brezhoneg",
    "es": "Español",
    "pt-BR": "Português (Brasil)",
    "pt-PT": "Português (Portugal)",
    "ca": "Català",
    "eu": "Euskara",
    "gl": "Galego",
    "it": "Italiano",
    "nl": "Nederlands",
    "af": "Afrikaans",
    "ar": "العربية",
    "fa": "فارسی",
    "da": "Dansk",
    "nb": "Norsk bokmål",
    "nn": "Norsk nynorsk",
    "sv": "Svenska",
    "is": "Íslenska",
    "fi": "Suomi",
    "pl": "Polski",
    "cs": "Čeština",
    "sk": "Slovenčina",
    "sl": "Slovenščina",
    "hr": "Hrvatski",
    "sr": "Српски",
    "hu": "Magyar",
    "ro": "Română",
    "lt": "Lietuvių",
    "lv": "Latviešu",
    "et": "Eesti",
    "ru": "Русский",
    "uk": "Українська",
    "bg": "Български",
    "el": "Ελληνικά",
    "ka": "ქართული",
    "mn": "Монгол",
    "tr": "Türkçe",
    "ur": "اردو",
    "pa-Arab": "پنجابی (شاہ مکھی)",
    "hi": "हिन्दी",
    "bn": "বাংলা",
    "ta": "தமிழ்",
    "ml": "മലയാളം",
    "ja": "日本語",
    "ko": "한국어",
    "th": "ไทย",
    "km": "ខ្មែរ",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "tl": "Tagalog",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
}

#: Where a bare language with more than one catalogue goes: `en`, `pt` and `zh`
#: name no territory, and CLDR's likely subtags say which one they imply.
#: Following CLDR rather than picking is what makes this answerable rather than
#: an opinion about who owns a language.
#:
#: `no` and `fil` are the exceptions, a language rather than a territory left
#: open. `no` is Norwegian without naming a written standard, and goes to
#: Bokmål, which most Norwegians write; Nynorsk (`nn`) has a catalogue of its
#: own and is not sent there. `fil` is Filipino, the standardised Tagalog that browsers
#: in the Philippines report, and reads the Tagalog catalogue.
DEFAULT_VARIANTS: dict[str, str | None] = {
    "en": "en-US",
    "fil": "tl",
    "no": "nb",
    # Bare Punjabi implies Gurmukhi in CLDR. Only Shahmukhi is translated here.
    "pa": None,
    "pt": "pt-BR",
    "zh": "zh-CN",
}

#: The region and script subtags that pick a variant, lowercased.
#:
#: A territory with no catalogue of its own is sent to the one it reads: Ireland
#: and Australia spell as Britain does, Angola and Mozambique write European
#: Portuguese, and Hong Kong and Macau read Traditional characters. A subtag
#: absent here falls through to `DEFAULT_VARIANTS`, so `en-CA` is American
#: rather than nothing.
VARIANT_SUBTAGS: dict[str, dict[str, str | None]] = {
    "en": {
        "us": "en-US",
        "au": "en-GB",
        "gb": "en-GB",
        "ie": "en-GB",
        "in": "en-GB",
        "nz": "en-GB",
        "uk": "en-GB",
        "za": "en-GB",
    },
    "fil": {},  # One catalogue, Tagalog; see `DEFAULT_VARIANTS`.
    "no": {},  # One catalogue, Bokmål; see `DEFAULT_VARIANTS`.
    "pa": {
        "arab": "pa-Arab",
        "guru": None,  # An explicit script wins even with a Pakistani region.
        "pk": "pa-Arab",
    },
    "pt": {
        "br": "pt-BR",
        "ao": "pt-PT",
        "cv": "pt-PT",
        "gw": "pt-PT",
        "mz": "pt-PT",
        "pt": "pt-PT",
        "st": "pt-PT",
        "tl": "pt-PT",
    },
    "zh": {
        "cn": "zh-CN",
        "hans": "zh-CN",
        "sg": "zh-CN",
        "hant": "zh-TW",
        "hk": "zh-TW",
        "mo": "zh-TW",
        "tw": "zh-TW",
    },
}

#: The language used when a request carries no usable preference at all.
DEFAULT_LANGUAGE = "en-US"


def normalise_language(value: str | None) -> str | None:
    """Return a stored language tag, or ``None`` for "follow the browser".

    A tag is narrowed to the catalogue that answers it. For most languages that
    means dropping the region -- ``de-AT`` is stored as ``de`` -- because the
    region reaches only the shape of a date, which the browser supplies
    separately. For the three languages written differently in different places
    the region is kept and, where it names a territory with no catalogue of its
    own, translated to the one that territory reads.

    Raises:
        InvalidInputError: The tag names a language with no catalogue.
    """
    if value is None or value == "":
        return None

    subtags = value.strip().replace("_", "-").split("-")
    language = subtags[0].lower()

    if language in LANGUAGES:
        return language

    variants = VARIANT_SUBTAGS.get(language)
    if variants is None:
        raise InvalidInputError(f"Unsupported language '{value}'")

    matched = DEFAULT_VARIANTS[language]
    for subtag in subtags[1:]:
        if subtag.lower() in variants:
            matched = variants[subtag.lower()]
            break
    if matched is None:
        raise InvalidInputError(f"Unsupported language '{value}'")
    return matched


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
