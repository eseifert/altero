"""Zotero object keys.

Every item, collection and saved search is identified within its library by an
eight-character key drawn from a reduced alphabet. Clients may supply their own
keys when creating objects, which is how parent/child relationships are expressed
in a single request, so keys must be validated as well as generated.
"""

import re
import secrets
import string

#: Alphabet used by Zotero object keys, as documented for the v3 API. The digits
#: 0 and 1 and the letter O are omitted; the remaining digits and uppercase
#: letters are all used.
KEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"

#: Number of characters in an object key.
KEY_LENGTH = 8

_KEY_PATTERN = re.compile(f"^[{KEY_ALPHABET}]{{{KEY_LENGTH}}}$")


def generate_key() -> str:
    """Return a new random object key."""
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))


def is_valid_key(key: str) -> bool:
    """Return whether ``key`` is a well-formed object key."""
    return _KEY_PATTERN.match(key) is not None


def coerce_key(key: str | None) -> str:
    """Return ``key`` if the client supplied a valid one, otherwise a fresh key.

    Raises:
        ValueError: if the client supplied a key that is not well-formed.
    """
    if not key:
        return generate_key()
    if not is_valid_key(key):
        raise ValueError(f"'{key}' is not a valid object key")
    return key


#: Alphabet used by API keys. Unlike object keys these are not read aloud, so
#: the full alphanumeric range is used.
API_KEY_ALPHABET = string.ascii_letters + string.digits

#: Number of characters in an API key.
API_KEY_LENGTH = 24


def generate_api_key() -> str:
    """Return a new random API key."""
    return "".join(secrets.choice(API_KEY_ALPHABET) for _ in range(API_KEY_LENGTH))
