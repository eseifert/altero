"""TOTP, checked against the vectors published in RFC 6238.

The appendix of RFC 6238 tabulates codes for a known seed at known instants.
Those are the only authority worth testing against here: an implementation that
agrees with itself proves nothing, and a second factor that disagrees with
every authenticator app is worse than none, because it locks the owner out of
their own library.
"""

import base64
import time

import pytest

from altero.services import totp

#: The ASCII seed the RFC uses for its SHA-1 vectors, as an authenticator app
#: would carry it.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()

#: Instant and expected eight-digit code, from the table in RFC 6238 appendix B.
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("timestamp", "expected"), RFC_VECTORS)
def test_code_matches_the_rfc_6238_vectors(timestamp: int, expected: str) -> None:
    assert totp.code_at(RFC_SECRET, timestamp, digits=8) == expected


def test_codes_are_six_digits_by_default() -> None:
    code = totp.code_at(RFC_SECRET, 59)

    assert code == "287082"
    assert len(code) == 6


def test_a_secret_is_accepted_with_or_without_base32_padding() -> None:
    unpadded = RFC_SECRET.rstrip("=")

    assert totp.code_at(unpadded, 59, digits=8) == "94287082"


def test_a_secret_is_accepted_in_lowercase_and_with_spaces() -> None:
    spaced = " ".join(RFC_SECRET[i : i + 4] for i in range(0, len(RFC_SECRET), 4)).lower()

    assert totp.code_at(spaced, 59, digits=8) == "94287082"


def test_a_malformed_secret_is_rejected_rather_than_silently_hashed() -> None:
    with pytest.raises(ValueError, match="not valid base32"):
        totp.code_at("not!valid!base32", 59)


def test_the_code_holds_for_a_whole_step_and_then_changes() -> None:
    assert totp.code_at(RFC_SECRET, 30) == totp.code_at(RFC_SECRET, 59)
    assert totp.code_at(RFC_SECRET, 60) != totp.code_at(RFC_SECRET, 59)


def test_verify_accepts_the_current_code() -> None:
    code = totp.code_at(RFC_SECRET, 1111111111)

    assert totp.verify(RFC_SECRET, code, timestamp=1111111111) is not None


def test_verify_accepts_one_step_either_side() -> None:
    #: A phone whose clock is half a minute out must still be usable.
    previous = totp.code_at(RFC_SECRET, 1111111111 - 30)
    following = totp.code_at(RFC_SECRET, 1111111111 + 30)

    assert totp.verify(RFC_SECRET, previous, timestamp=1111111111) is not None
    assert totp.verify(RFC_SECRET, following, timestamp=1111111111) is not None


def test_verify_rejects_a_code_two_steps_away() -> None:
    stale = totp.code_at(RFC_SECRET, 1111111111 - 90)

    assert totp.verify(RFC_SECRET, stale, timestamp=1111111111) is None


def test_verify_rejects_a_wrong_code() -> None:
    assert totp.verify(RFC_SECRET, "000000", timestamp=1111111111) is None


def test_verify_rejects_a_code_that_is_not_digits() -> None:
    assert totp.verify(RFC_SECRET, "abcdef", timestamp=1111111111) is None
    assert totp.verify(RFC_SECRET, "", timestamp=1111111111) is None


def test_verify_ignores_spaces_a_user_typed() -> None:
    code = totp.code_at(RFC_SECRET, 1111111111)
    spaced = f"{code[:3]} {code[3:]}"

    assert totp.verify(RFC_SECRET, spaced, timestamp=1111111111) is not None


def test_verify_returns_the_step_it_matched_so_replay_can_be_refused() -> None:
    """The caller stores the returned step and refuses anything not above it.

    Without this a code stays valid for its whole window, and shoulder-surfing
    or a replayed request gets a second use out of it.
    """
    timestamp = 1111111111
    current = totp.code_at(RFC_SECRET, timestamp)
    previous = totp.code_at(RFC_SECRET, timestamp - 30)

    assert totp.verify(RFC_SECRET, current, timestamp=timestamp) == timestamp // 30
    assert totp.verify(RFC_SECRET, previous, timestamp=timestamp) == (timestamp - 30) // 30


def test_verify_defaults_to_now() -> None:
    code = totp.code_at(RFC_SECRET, int(time.time()))

    assert totp.verify(RFC_SECRET, code) is not None


def test_generated_secrets_are_base32_and_unpredictable() -> None:
    secrets = {totp.generate_secret() for _ in range(50)}

    assert len(secrets) == 50
    for secret in secrets:
        # Decodes, and carries at least the 128 bits RFC 4226 requires.
        assert len(base64.b32decode(secret, casefold=True)) >= 16
        assert totp.code_at(secret, 0)


def test_the_provisioning_uri_is_what_an_authenticator_scans() -> None:
    uri = totp.provisioning_uri(RFC_SECRET, account="ada", issuer="altero")

    assert uri.startswith("otpauth://totp/altero:ada?")
    assert f"secret={RFC_SECRET}" in uri
    assert "issuer=altero" in uri
    assert "digits=6" in uri
    assert "period=30" in uri


def test_the_provisioning_uri_escapes_an_account_with_awkward_characters() -> None:
    uri = totp.provisioning_uri(RFC_SECRET, account="a b/c", issuer="al tero")

    assert " " not in uri
    assert "a%20b%2Fc" in uri
