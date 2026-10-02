"""SIGKILL the serving process after commit and restart over persistent state."""

import asyncio

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def server_crash(run: AcceptanceRun) -> None:
    await run.phase("A", files=False)
    await run.phase("B", files=False)
    barrier = run.server.barrier
    barrier.arm("POST", "/users/1/items", "response")
    interrupted = asyncio.Event()
    pending = asyncio.create_task(
        run.phase("A", [dict(action="create", key="CRASH234")], files=False, interrupt=interrupted)
    )
    assert run.server.crash is not None
    assert run.server.restart is not None
    try:
        async with asyncio.timeout(60):
            await barrier.reached.wait()
        assert barrier.trace[-1]["status"] == 200, "Server did not commit before crashing"
        old_pid = await run.server.crash()
        interrupted.set()
        assert (await pending).get("interrupted")
    finally:
        barrier.release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    new_pid = await run.server.restart()
    assert new_pid != old_pid, "The serving process was not replaced"
    data = (await run.request("GET", "/users/1/items/CRASH234")).json()["data"]
    assert data["version"] == 1
    left, right = await run.phase("A", files=False), await run.phase("B", files=False)
    await run.converged(left, right)
    assert len(left["items"]) == 1
    assert left["items"][0]["version"] == 1, "Recovery duplicated the uncertain commit"
    await run.settled(files=False)
