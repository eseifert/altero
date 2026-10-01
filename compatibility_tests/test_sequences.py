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
