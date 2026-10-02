"""A crash run replaces the serving process while preserving its real database."""

import asyncio
from contextlib import suppress

import httpx

from tools.compatibility.process_server import process_server


async def test_committed_object_survives_killed_worker(tmp_path):
    async with process_server(tmp_path / "server") as server:
        headers = {"Zotero-API-Key": server.key}
        async with httpx.AsyncClient(base_url=server.url) as client:
            server.barrier.arm("POST", "/users/1/items", "response")
            pending = asyncio.create_task(
                client.post(
                    "/users/1/items",
                    headers=headers,
                    json=[dict(key="CRASH234", itemType="book", title="Durable")],
                )
            )
            try:
                async with asyncio.timeout(10):
                    await server.barrier.reached.wait()
                assert server.barrier.trace[-1]["status"] == 200
                assert server.crash is not None
                old_pid = await server.crash()
                with suppress(httpx.TransportError):
                    await pending
            finally:
                server.barrier.release.set()
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            assert server.restart is not None
            assert await server.restart() != old_pid
            response = await client.get("/users/1/items/CRASH234", headers=headers)
            assert response.status_code == 200
            assert response.json()["data"]["title"] == "Durable"
            assert response.json()["version"] == 1
