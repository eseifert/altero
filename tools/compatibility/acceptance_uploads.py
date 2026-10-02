"""Kill an actual desktop after the server has consumed only part of an upload."""

import asyncio
import base64
import random

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def upload_interruption(run: AcceptanceRun) -> None:
    await run.phase("A", [dict(action="create", key="UPLNAD23")])
    await run.phase("B")
    path = run.root / "large.bin"
    # Incompressible bytes exceed socket buffers: the desktop is still sending
    # when the ASGI receiver reaches its first chunk, rather than just waiting
    # for a reply to an already completely transmitted compressed ZIP.
    content = random.Random(105).randbytes(16 * 1024 * 1024)
    path.write_bytes(content)
    created = await run.phase(
        "A", [dict(action="attach", key="UPLNAD23", path=str(path))], sync=False
    )
    key = next(iter(created["files"]))
    barrier = run.server.barrier
    barrier.arm("POST", "/storage/upload/", "upload", prefix=True)
    interrupted = asyncio.Event()
    pending = asyncio.create_task(run.phase("A", interrupt=interrupted))
    try:
        async with asyncio.timeout(60):
            await barrier.reached.wait()
        assert barrier.trace[-1]["more_body"], "Upload was already fully buffered"
        assert 0 < barrier.trace[-1]["consumed_bytes"] < len(content)
        # Registration must not precede the incomplete byte transfer.
        data = (await run.request("GET", f"/users/1/items/{key}")).json()["data"]
        assert not data.get("md5"), "Partial bytes were registered as a complete file"
        interrupted.set()
        assert (await pending).get("interrupted"), "Desktop was not interrupted during upload"
    finally:
        barrier.release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    left, right = await run.phase("A"), await run.phase("B")
    await run.converged(left, right)
    assert right["files"][key] == base64.b64encode(content).decode()
    assert right["storage_states"][key] == left["storage_states"][key] == "in_sync"
    await run.settled()
