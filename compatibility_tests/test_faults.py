"""Injected failures exercise real transport boundaries and durable writes."""

import httpx
import pytest

from tools.compatibility.barriers import HTTPBarrier
from tools.compatibility.runtime import disposable_server


@pytest.mark.parametrize(("point", "committed"), [("before", False), ("response", True)])
async def test_transient_response_distinguishes_uncommitted_and_committed_writes(
    tmp_path, point, committed
):
    async with disposable_server(tmp_path / "server") as server:
        barrier = server.barrier
        barrier.inject("POST", "/users/1/items", point, fault="status", status=503)
        async with httpx.AsyncClient(
            base_url=server.url, headers={"Zotero-API-Key": server.key}
        ) as client:
            failed = await client.post(
                "/users/1/items", json=[dict(key="FAULT234", itemType="book", title="Durable")]
            )
            assert failed.status_code == 503
            assert barrier.reached.is_set()
            stored = (await client.get("/users/1/items")).json()
            assert bool(stored) == committed
            retried = await client.post(
                "/users/1/items",
                headers={"If-Unmodified-Since-Version": "0"},
                json=[dict(key="FAULT234", itemType="book", title="Durable")],
            )
            assert retried.status_code == (412 if committed else 200)
            assert len((await client.get("/users/1/items")).json()) == 1
            assert (await client.get("/users/1/items")).headers["Last-Modified-Version"] == "1"


async def test_truncated_response_is_a_real_transport_error_and_next_request_recovers(tmp_path):
    async with (
        disposable_server(tmp_path / "server") as server,
        httpx.AsyncClient(base_url=server.url, headers={"Zotero-API-Key": server.key}) as client,
    ):
        barrier = server.barrier
        barrier.inject("GET", "/users/1/items", "download", fault="disconnect")
        with pytest.raises(httpx.RemoteProtocolError):
            await client.get("/users/1/items")
        assert barrier.reached.is_set()
        assert (await client.get("/users/1/items")).status_code == 200


def test_impossible_fault_configuration_is_rejected_before_arming():
    barrier = HTTPBarrier()
    with pytest.raises(ValueError, match="Status faults"):
        barrier.inject("POST", "/items", "before", fault="status", status=200)
    assert not barrier.active
