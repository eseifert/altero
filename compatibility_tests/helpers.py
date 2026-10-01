"""Shared live-replay helpers; assertions stay in the scenario tests."""

from tools.compatibility.library import LibraryReplay as LibraryReplay

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"


def object_key(index: int) -> str:
    """Deterministic valid keys; Zotero excludes 0, 1 and O."""
    alphabet = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
    result = ""
    for _ in range(8):
        index, digit = divmod(index, len(alphabet))
        result = alphabet[digit] + result
    return result
