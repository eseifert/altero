"""A real validator refuses a corrupted new parent and its dependent child."""

import asyncio

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def parent_rejection(run: AcceptanceRun) -> None:
    await run.phase("A", files=False)
    await run.phase("B", files=False)
    await run.phase(
        "A",
        [
            dict(action="create", key="PARENT23"),
            dict(
                action="create",
                key="CHILD234",
                data=dict(itemType="note", parentItem="PARENT23", note="<p>Pending child</p>"),
            ),
            dict(action="create", key="SUCCESS2"),
        ],
        sync=False,
        files=False,
    )
    # Only the outgoing parent's type is corrupted. The real desktop queue,
    # dependent child, server validator and per-object error handling run intact.
    barrier = run.server.barrier
    barrier.arm("POST", "/users/1/items", rewrite_item=dict(key="PARENT23", itemType="invalid"))
    barrier.release.set()
    response = barrier.fork()
    response.arm("POST", "/users/1/items", "response")
    pending = asyncio.create_task(
        run.phase(
            "A",
            files=False,
            expected_upload_errors=[dict(code=400, key="PARENT23")],
        )
    )
    try:
        async with asyncio.timeout(60):
            await response.reached.wait()
        stored = (await run.request("GET", "/users/1/items")).json()
        assert {item["key"] for item in stored} == {"SUCCESS2"}, (
            "Rejected parent left an orphan or lost unrelated success"
        )
        response.release.set()
        recovered = await pending
    finally:
        response.release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    assert barrier.reached.is_set()
    assert not recovered["unsynced"]["item"], "Original retry failed to recover parent and child"
    assert (
        next(item for item in recovered["items"] if item["key"] == "CHILD234")["note"]
        == "<p>Pending child</p>"
    )
    await run.converged(recovered, await run.phase("B", files=False))
    await run.settled(files=False)
