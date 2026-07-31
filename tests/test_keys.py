"""Tests for Zotero object keys."""

import pytest

from altero.keys import KEY_ALPHABET, KEY_LENGTH, coerce_key, generate_key, is_valid_key


def test_generated_keys_have_the_documented_shape() -> None:
    for _ in range(100):
        key = generate_key()
        assert len(key) == KEY_LENGTH
        assert set(key) <= set(KEY_ALPHABET)


def test_generated_keys_are_valid() -> None:
    assert all(is_valid_key(generate_key()) for _ in range(100))


def test_generated_keys_differ() -> None:
    assert len({generate_key() for _ in range(100)}) > 1


@pytest.mark.parametrize("key", ["ABCD2345", "22222222", "ZZZZZZZZ"])
def test_valid_keys_are_accepted(key: str) -> None:
    assert is_valid_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "ABCD234",  # too short
        "ABCD23456",  # too long
        "abcd2345",  # lowercase
        "ABCD2340",  # zero is not in the alphabet
        "ABCD2341",  # one is not in the alphabet
        "ABCDO345",  # letter O is not in the alphabet
        "ABCD-345",
    ],
)
def test_invalid_keys_are_rejected(key: str) -> None:
    assert not is_valid_key(key)


def test_the_alphabet_matches_the_documented_one() -> None:
    assert KEY_ALPHABET == "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
    assert set("01O") & set(KEY_ALPHABET) == set()


def test_coerce_key_generates_when_none_is_supplied() -> None:
    assert is_valid_key(coerce_key(None))
    assert is_valid_key(coerce_key(""))


def test_coerce_key_keeps_a_client_supplied_key() -> None:
    assert coerce_key("ABCD2345") == "ABCD2345"


def test_coerce_key_rejects_a_malformed_client_key() -> None:
    with pytest.raises(ValueError, match="not a valid"):
        coerce_key("nope")
