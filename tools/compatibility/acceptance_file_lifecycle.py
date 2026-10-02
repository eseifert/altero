"""File names, shared digests and stale download permissions survive real clients."""

import asyncio
import base64
import hashlib
import time

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def file_lifecycle(run: AcceptanceRun) -> None:
    content = b"Shared attachment bytes"
    path = run.root / "Über 東京.txt"
    path.write_bytes(content)
    first = await run.phase(
        "A",
        [
            dict(action="create", key="LIFECYC2"),
            dict(action="attach", key="LIFECYC2", path=str(path)),
        ],
    )
    await run.converged(first, await run.phase("B"))
    first = await run.phase("A", [dict(action="attach", key="LIFECYC2", path=str(path))])
    keys = sorted(first["files"])
    assert len(keys) == 2
    await run.converged(first, await run.phase("B"))
    renamed = await run.phase(
        "A", [dict(action="rename-file", key=keys[0], name="Renamed 研究.txt")]
    )
    received = await run.phase("B")
    await run.converged(renamed, received)
    assert list(received["file_entries"][keys[0]]) == ["Renamed 研究.txt"]
    remaining = await run.phase("A", [dict(action="delete", key=keys[0])])
    await run.converged(remaining, await run.phase("B"))
    assert remaining["files"] == {keys[1]: base64.b64encode(content).decode()}
    # A normal 10.0.5 sync detects the missing file and recovers the other reference.
    recovered = await run.phase("B", [dict(action="remove-file", key=keys[1])])
    await run.converged(remaining, recovered)
    assert recovered["storage_states"][keys[1]] == "in_sync"
    await run.phase("B", [dict(action="remove-file", key=keys[1])], sync=False)
    barrier = run.server.barrier
    start = len(barrier.requests)
    barrier.arm("GET", "/storage/download/", prefix=True)
    pending = asyncio.create_task(run.phase("B", expected_file_sync_error=True))
    replacement = run.root / "changed.txt"
    replacement.write_bytes(b"New attachment bytes")
    try:
        async with asyncio.timeout(60):
            await barrier.reached.wait()
        await run.phase(
            "A",
            [
                dict(
                    action="replace-file",
                    key=keys[1],
                    path=str(replacement),
                    mtime=time.time_ns() // 1_000_000 + 10000,
                )
            ],
        )
    except BaseException:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        raise
    finally:
        barrier.release.set()
    stale = await pending
    assert stale["files"][keys[1]] is None, "Rejected redirect installed a local file"
    assert any(
        request["path"].startswith("/storage/download/") and request.get("status") == 404
        for request in barrier.requests[start:]
    ), "A stale redirect was allowed to fetch different bytes"
    left, right = await run.phase("A"), await run.phase("B")
    await run.converged(left, right)
    assert right["files"][keys[1]] == base64.b64encode(replacement.read_bytes()).decode()
    data = (await run.request("GET", f"/users/1/items/{keys[1]}")).json()["data"]
    assert data["md5"] == hashlib.md5(replacement.read_bytes()).hexdigest()
    await run.settled()
