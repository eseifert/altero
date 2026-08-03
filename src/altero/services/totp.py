"""Time-based one-time passwords, as specified by RFC 6238.

Hand-rolled rather than taken from a package, because the whole of it is the
HMAC below and because RFC 6238 publishes test vectors: the implementation can
be held against the standard itself instead of against another implementation's
opinion of it. ``tests/test_totp.py`` does exactly that.

Nothing here reads the clock unless asked to. ``timestamp`` is an argument so
that the tests can stand at a known instant, which is what makes the RFC's
table usable at all.
"""

import base64
import binascii
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

#: Seconds per step. Thirty is what every authenticator app assumes.
STEP_SECONDS = 30

#: Digits in a generated code. Six is the universal default.
DIGITS = 6

#: How many steps either side of the current one are accepted. One step covers
#: a phone clock that is up to thirty seconds out, which is common enough that
#: refusing it would produce support requests rather than security.
WINDOW = 1

#: Bytes of entropy in a generated secret. RFC 4226 requires at least 128 bits
#: and recommends 160, which is also what a SHA-1 HMAC consumes.
SECRET_BYTES = 20


def normalise_secret(secret: str) -> bytes:
    """Return the raw bytes of a base32 ``secret`` as a user might have typed it.

    Authenticator apps display secrets in lowercase groups of four and drop the
    padding, and users paste what they see. All of that is accepted; anything
    that is genuinely not base32 raises rather than being hashed as-is, since a
    silently mangled secret produces codes that never match and no clue why.
    """
    compact = secret.replace(" ", "").replace("-", "").upper()
    # b32decode demands the padding that the apps omit.
    padded = compact + "=" * (-len(compact) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Secret is not valid base32") from error


def generate_secret() -> str:
    """Return a fresh base32 secret suitable for an authenticator app."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode()


def code_at(
    secret: str,
    timestamp: int,
    *,
    digits: int = DIGITS,
    step: int = STEP_SECONDS,
) -> str:
    """Return the code for ``secret`` at ``timestamp``, zero-padded to ``digits``."""
    return _code_for_step(secret, timestamp // step, digits=digits)


def _code_for_step(secret: str, counter: int, *, digits: int = DIGITS) -> str:
    """Return the HOTP code for ``counter``, which is RFC 4226 section 5.3."""
    digest = hmac.new(normalise_secret(secret), struct.pack(">Q", counter), "sha1").digest()
    # Dynamic truncation: the low nibble of the last byte picks the offset, and
    # the high bit of the extracted word is masked off so the result is
    # positive on every platform.
    offset = digest[-1] & 0x0F
    (truncated,) = struct.unpack(">I", digest[offset : offset + 4])
    return str((truncated & 0x7FFFFFFF) % 10**digits).zfill(digits)


def verify(
    secret: str,
    code: str,
    timestamp: int | None = None,
    *,
    digits: int = DIGITS,
    step: int = STEP_SECONDS,
    window: int = WINDOW,
) -> int | None:
    """Return the step ``code`` matched, or ``None`` if it matched none.

    The step is returned rather than a boolean so that the caller can record it
    and refuse anything at or below it next time. A code is valid for a whole
    step plus the window either side, and without that record it can be used
    again for the rest of that period by whoever else saw it.
    """
    from time import time

    candidate = code.replace(" ", "").replace("-", "")
    if not candidate.isdigit():
        return None

    now = int(time()) if timestamp is None else timestamp
    current = now // step
    for offset in range(-window, window + 1):
        counter = current + offset
        if hmac.compare_digest(_code_for_step(secret, counter, digits=digits), candidate):
            return counter
    return None


def provisioning_uri(
    secret: str,
    *,
    account: str,
    issuer: str,
    digits: int = DIGITS,
    step: int = STEP_SECONDS,
) -> str:
    """Return the ``otpauth://`` URI an authenticator app scans as a QR code.

    The label repeats the issuer before the account name, which is the Key URI
    format's convention and what makes the entry legible in an app holding
    accounts from several servers.
    """
    # The separating colon stays literal, as in the Key URI format's own
    # examples; only the two names around it are escaped. Escaping the colon
    # too would leave apps showing one run-together string instead of an
    # issuer and an account.
    label = f"{quote(issuer, safe='')}:{quote(account, safe='')}"
    parameters = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": digits,
            "period": step,
        },
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{parameters}"
