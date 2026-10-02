"""Matching desktop copies must still agree with the server and finish uploads."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from tools.compatibility.acceptance_runtime import AcceptanceRun
from tools.compatibility.runtime import TestServer as DisposableServer


@pytest.mark.parametrize("failure", ["server-title", "server-version", "desktop-title", "pending"])
async def test_convergence_rejects_divergent_state(tmp_path, failure):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.1", tmp_path, DisposableServer("http://localhost")
    )
    snapshot: dict = dict(
        items=[dict(key="ABCD2345", version=1, itemType="book", title="Kept", creators=[])],
        collections=[],
        searches=[],
        files={},
        unsynced=dict(item=[], collection=[], search=[]),
    )
    server = {kind: deepcopy(snapshot[kind]) for kind in ("items", "collections", "searches")}

    async def request(method, path, **options):
        return httpx.Response(200, json=[{"data": value} for value in server[path.split("/")[-1]]])

    runner.request = AsyncMock(side_effect=request)
    await runner.converged(snapshot, deepcopy(snapshot))
    other = deepcopy(snapshot)
    if failure == "server-title":
        server["items"][0]["title"] = "Lost"
    elif failure == "server-version":
        server["items"][0]["version"] = 0
    elif failure == "desktop-title":
        other["items"][0]["title"] = "Different"
    else:
        other["unsynced"]["item"] = [1]
    with pytest.raises(AssertionError):
        await runner.converged(snapshot, other)


async def test_collection_membership_order_is_not_a_conflict(tmp_path):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.1", tmp_path, DisposableServer("http://localhost")
    )
    snapshot: dict = dict(
        items=[
            dict(key="ABCD2345", version=1, itemType="book", collections=["BBBB2345", "AAAA2345"])
        ],
        collections=[],
        searches=[],
        files={},
        unsynced=dict(item=[], collection=[], search=[]),
    )

    async def request(method, path, **options):
        return httpx.Response(
            200, json=[{"data": value} for value in snapshot[path.split("/")[-1]]]
        )

    runner.request = AsyncMock(side_effect=request)
    other = deepcopy(snapshot)
    other["items"][0]["collections"].reverse()
    await runner.converged(snapshot, other)
    other["items"][0]["collections"].pop()
    with pytest.raises(AssertionError):
        await runner.converged(snapshot, other)
