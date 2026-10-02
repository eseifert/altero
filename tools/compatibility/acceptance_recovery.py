"""Restart a killed desktop after an uncertain commit and race actual writers."""

import asyncio
import base64

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def recovery(run: AcceptanceRun) -> None:
    # Initialize both actual databases before interruption; startup failures
    # must never count as recovery of an interrupted request.
    await run.phase("A", files=False)
    await run.phase("B", files=False)
    barrier = run.server.barrier
    barrier.arm("POST", "/users/1/items", "response")
    interrupted = asyncio.Event()
    pending = asyncio.create_task(
        run.phase("A", [dict(action="create", key="RESTART2")], files=False, interrupt=interrupted)
    )
    try:
        async with asyncio.timeout(60):
            await barrier.reached.wait()
        assert barrier.trace[-1]["status"] == 200, "No committed upload reached the barrier"
        interrupted.set()
        stopped = await pending
        assert stopped.get("interrupted"), "Desktop exited normally before the interruption"
    finally:
        barrier.release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    persisted = (await run.request("GET", "/users/1/items/RESTART2")).json()["data"]
    assert persisted["title"] == "Über 東京"
    restored = await run.phase("A", files=False)
    await run.converged(restored, await run.phase("B", files=False))
    assert restored["items"][0]["version"] == persisted["version"], "Retry duplicated a commit"
    # Warm profiles each have pending work. Launch both original runners together.
    await run.phase("A", [dict(action="create", key="WRITER23")], sync=False, files=False)
    await run.phase("B", [dict(action="create", key="WRITER24")], sync=False, files=False)
    await asyncio.gather(run.phase("A", files=False), run.phase("B", files=False))
    left, right = await run.phase("A", files=False), await run.phase("B", files=False)
    await run.converged(left, right)
    assert {item["key"] for item in left["items"]} == {"RESTART2", "WRITER23", "WRITER24"}
    watermark = (await run.request("GET", "/users/1/items?format=versions")).headers[
        "Last-Modified-Version"
    ]
    await asyncio.gather(run.phase("A", files=False), run.phase("B", files=False))
    assert (await run.request("GET", "/users/1/items?format=versions")).headers[
        "Last-Modified-Version"
    ] == watermark, "Recovered writers keep changing the library"
    payload = b"%PDF-1.4\n" + b"Disposable transfer bytes\n" * 8192 + b"%%EOF\n"
    path = run.root / "interrupted.pdf"
    path.write_bytes(payload)
    attached = await run.phase("A", [dict(action="attach", key="RESTART2", path=str(path))])
    key = next(iter(attached["files"]))
    barrier.arm("GET", "/storage/download/", "download", prefix=True)
    interrupted.clear()
    pending = asyncio.create_task(run.phase("B", interrupt=interrupted))
    try:
        async with asyncio.timeout(60):
            await barrier.reached.wait()
        interrupted.set()
        assert (await pending).get("interrupted"), "No desktop was killed during download"
    finally:
        barrier.release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    downloaded = await run.phase("B")
    await run.converged(attached, downloaded)
    assert downloaded["files"][key] == base64.b64encode(payload).decode()
    assert downloaded["storage_states"][key] == "in_sync", "Interrupted transfer remains pending"
