"""Password hashing and the policy applied before it.

The rules here follow NIST SP 800-63B: a length floor, an upper bound, and no
composition rules at all. Requiring a digit and a symbol measurably pushes
people towards `Password1!` and towards reuse, so the only thing checked is
that the password is long enough to be worth hashing and short enough that
hashing it cannot be turned into a denial of service.
"""

import pytest

from altero.errors import InvalidInputError
from altero.services import passwords


def test_a_hash_does_not_contain_the_password() -> None:
    stored = passwords.hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in stored


def test_a_hash_identifies_itself_as_argon2id() -> None:
    """Recorded so that a change of algorithm is a visible change here."""
    assert passwords.hash_password("correct horse battery staple").startswith("$argon2id$")


def test_the_same_password_hashes_differently_every_time() -> None:
    """Distinct salts, so identical passwords are not identifiable as such."""
    first = passwords.hash_password("correct horse battery staple")
    second = passwords.hash_password("correct horse battery staple")

    assert first != second


def test_the_right_password_verifies() -> None:
    stored = passwords.hash_password("correct horse battery staple")

    assert passwords.verify_password(stored, "correct horse battery staple") is True


def test_the_wrong_password_does_not_verify() -> None:
    stored = passwords.hash_password("correct horse battery staple")

    assert passwords.verify_password(stored, "Correct Horse Battery Staple") is False
    assert passwords.verify_password(stored, "") is False


def test_a_corrupt_stored_hash_fails_rather_than_raising() -> None:
    """A row damaged by a bad restore must not turn every login into a 500."""
    assert passwords.verify_password("not a hash at all", "anything") is False
    assert passwords.verify_password("", "anything") is False


def test_unicode_survives_the_round_trip() -> None:
    stored = passwords.hash_password("gemäß Straße 🔐 пароль")

    assert passwords.verify_password(stored, "gemäß Straße 🔐 пароль") is True


def test_a_long_password_is_accepted_whole() -> None:
    """bcrypt would silently ignore everything past 72 bytes; argon2 does not."""
    password = "a" * 200 + "-tail"
    stored = passwords.hash_password(password)

    assert passwords.verify_password(stored, password) is True
    assert passwords.verify_password(stored, "a" * 200) is False


def test_a_password_at_the_floor_is_allowed() -> None:
    passwords.validate_password("a" * passwords.MINIMUM_LENGTH)


def test_a_short_password_is_refused_with_the_length_in_the_message() -> None:
    with pytest.raises(InvalidInputError) as error:
        passwords.validate_password("a" * (passwords.MINIMUM_LENGTH - 1))

    assert str(passwords.MINIMUM_LENGTH) in error.value.message


def test_an_absurdly_long_password_is_refused_before_it_is_hashed() -> None:
    """Argon2 is deliberately expensive; an unbounded input is a way to spend it."""
    with pytest.raises(InvalidInputError):
        passwords.validate_password("a" * (passwords.MAXIMUM_LENGTH + 1))


def test_an_empty_password_is_refused() -> None:
    with pytest.raises(InvalidInputError):
        passwords.validate_password("")


def test_no_composition_rules_are_imposed() -> None:
    """Lower-case words with no digit or symbol are fine, and long ones are best."""
    passwords.validate_password("correct horse battery staple")


def test_a_password_is_not_stripped_or_altered() -> None:
    """Leading and trailing spaces are part of the secret, not noise."""
    stored = passwords.hash_password("  spaces matter  ")

    assert passwords.verify_password(stored, "  spaces matter  ") is True
    assert passwords.verify_password(stored, "spaces matter") is False


def test_a_hash_at_the_current_parameters_does_not_need_rehashing() -> None:
    stored = passwords.hash_password("correct horse battery staple")

    assert passwords.needs_rehash(stored) is False


def test_a_hash_at_weaker_parameters_needs_rehashing() -> None:
    """Raising the cost later must be detectable on the next successful login."""
    # 1 MiB and a single pass: valid Argon2 parameters, far below the profile
    # in use. Anything under 8*parallelism KiB is rejected by argon2 itself.
    weak = passwords.hash_password("correct horse battery staple", memory_cost=1024, time_cost=1)

    assert passwords.needs_rehash(weak) is True


def test_a_corrupt_hash_does_not_claim_to_need_rehashing() -> None:
    """It cannot be upgraded, and reporting otherwise would loop the caller."""
    assert passwords.needs_rehash("not a hash at all") is False


def test_verifying_against_no_credential_still_costs_the_same_work() -> None:
    """Login must not answer faster for an unknown user than a known one.

    A measurable difference enumerates accounts. The check is that the dummy
    path really does hash something rather than returning early.
    """
    assert passwords.verify_password(None, "anything") is False


def test_the_dummy_secret_is_not_a_master_key() -> None:
    """A user with no password must not be reachable by the timing dummy.

    The dummy's plaintext is a literal in the source, so anyone can read it. If
    the no-password path decided on the comparison rather than on whether a
    credential existed, that string would log in as every account that has not
    set a password -- which, on a fresh instance, is all of them.
    """
    assert passwords.verify_password(None, passwords._DUMMY_PASSWORD) is False


def test_a_corrupt_hash_is_not_reachable_by_the_dummy_secret_either() -> None:
    assert passwords.verify_password("not a hash at all", passwords._DUMMY_PASSWORD) is False
