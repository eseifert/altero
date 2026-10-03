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
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
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
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
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


async def test_convergence_reads_past_the_first_server_page(tmp_path):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
    )
    items = [dict(key=f"KEY{i:05d}", version=1, itemType="book") for i in range(101)]
    snapshot = dict(items=items, collections=[], searches=[], files={}, unsynced={})
    starts = []

    async def request(method, path, **options):
        values = items if path.endswith("/items") else []
        start = options["params"].get("start", 0)
        starts.append((path, start))
        return httpx.Response(200, json=[dict(data=value) for value in values[start : start + 100]])

    runner.request = AsyncMock(side_effect=request)
    await runner.converged(snapshot, deepcopy(snapshot))
    assert ("/users/1/items", 100) in starts


async def test_single_relation_wire_and_desktop_shapes_are_equivalent(tmp_path):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
    )
    snapshot = dict(
        items=[
            dict(
                key="ABCD2345",
                version=1,
                itemType="book",
                relations={"dc:relation": ["https://example.org/item"]},
            )
        ],
        collections=[],
        searches=[],
        files={},
        unsynced={},
    )
    server: dict = deepcopy(snapshot)
    server["items"][0]["relations"]["dc:relation"] = "https://example.org/item"

    async def request(method, path, **options):
        return httpx.Response(200, json=[dict(data=value) for value in server[path.split("/")[-1]]])

    runner.request = AsyncMock(side_effect=request)
    await runner.converged(snapshot, deepcopy(snapshot))
    server["items"][0]["relations"]["dc:relation"] = "https://example.org/lost"
    with pytest.raises(AssertionError):
        await runner.converged(snapshot, deepcopy(snapshot))


async def test_unchanged_upload_can_record_a_higher_desktop_object_version(tmp_path):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
    )
    snapshot: dict = dict(
        items=[dict(key="ABCD2345", version=7, itemType="book", title="Kept")],
        collections=[],
        searches=[],
        files={},
        unsynced={},
    )
    stored: dict = deepcopy(snapshot)
    stored["items"][0]["version"] = 2
    other = deepcopy(stored)

    async def request(method, path, **options):
        return httpx.Response(200, json=[dict(data=value) for value in stored[path.split("/")[-1]]])

    runner.request = AsyncMock(side_effect=request)
    await runner.converged(snapshot, other)
    stored["items"][0]["version"] = 8
    with pytest.raises(AssertionError):
        await runner.converged(snapshot, other)


async def test_last_read_wire_text_matches_desktop_integer_without_losing_changes(tmp_path):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
    )
    snapshot = dict(
        items=[dict(key="ABCD2345", version=1, itemType="attachment", lastRead=1785701798)],
        collections=[],
        searches=[],
        files={},
        unsynced={},
    )
    stored = deepcopy(snapshot)
    stored["items"][0]["lastRead"] = "1785701798"

    async def request(method, path, **options):
        return httpx.Response(200, json=[dict(data=value) for value in stored[path.split("/")[-1]]])

    runner.request = AsyncMock(side_effect=request)
    await runner.converged(snapshot, deepcopy(snapshot))
    stored["items"][0]["lastRead"] = "1785701799"
    with pytest.raises(AssertionError, match="Server items"):
        await runner.converged(snapshot, deepcopy(snapshot))


async def test_unchanged_setting_records_batch_version_and_still_checks_value(tmp_path):
    runner = AcceptanceRun(
        Path("/unused"), "10.0.5", tmp_path, DisposableServer("http://localhost")
    )
    snapshot: dict = dict(
        items=[],
        collections=[],
        searches=[],
        files={},
        unsynced={},
        settings={"lastPageIndex_u_ABCD2345": dict(value=0, version=4)},
    )
    other = deepcopy(snapshot)
    other["settings"]["lastPageIndex_u_ABCD2345"]["version"] = 6
    stored = deepcopy(snapshot["settings"])

    async def request(method, path, **options):
        return httpx.Response(200, json=stored if path.endswith("settings") else [])

    runner.request = AsyncMock(side_effect=request)
    await runner.converged(snapshot, other)
    stored["lastPageIndex_u_ABCD2345"]["version"] = 6
    await runner.converged(snapshot, other)
    stored["lastPageIndex_u_ABCD2345"]["value"] = 1
    with pytest.raises(AssertionError, match="settings"):
        await runner.converged(snapshot, other)
