"""Length and offline common-password checks precede credential writes."""

import pytest

from altero.errors import InvalidInputError
from altero.services import passwords


def test_common_passwords_are_blocked_without_composition_rules() -> None:
    for password in ["password123", " PASSWORD123 ", "123456789"]:
        with pytest.raises(InvalidInputError, match="common"):
            passwords.validate_password(password)
    passwords.validate_password("a long phrase made of ordinary lowercase words")


def test_configurable_length_and_explicit_blocklist_opt_out() -> None:
    policy = getattr(passwords, "PasswordPolicy", None)
    assert policy, "Configurable password policy must be implemented"
    with pytest.raises(InvalidInputError, match="16"):
        passwords.validate_password("unusualphrase", policy=policy(minimum_length=16))
    passwords.validate_password("password123", policy=policy(block_common=False))
