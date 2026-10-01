"""Reproducible transitions use a model independent of API response objects."""

import pytest

from tools.compatibility.sequences import check_sequence, generate_sequence, minimize


@pytest.mark.parametrize("seed", [4, 14, 91])
async def test_seeded_operation_sequence(desktop, seed):
    await check_sequence(desktop, generate_sequence(seed, 12))


async def test_shrinking_preserves_the_failure_and_removes_noise():
    async def fails(steps):
        return 2 in steps and 7 in steps

    reduced = await minimize(list(range(10)), fails)
    assert reduced == [2, 7]


def test_shrinking_rejects_steps_that_became_noops():
    from tools.compatibility.sequences import valid_sequence

    create = {"action": "create", "key": "ABCD2345", "title": "old"}
    trash = {"action": "trash", "key": "ABCD2345", "value": True}
    restore = {"action": "trash", "key": "ABCD2345", "value": False}
    assert valid_sequence([create, trash, restore])
    assert not valid_sequence([create, restore])
    assert not valid_sequence([create, {"action": "edit", "key": "ABCD2345", "title": "old"}])
    assert not valid_sequence([])
