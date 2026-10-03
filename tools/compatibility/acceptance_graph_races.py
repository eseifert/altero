"""Concurrent deletion and reparenting while a real desktop consumes old reads."""

import asyncio

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def graph_races(run: AcceptanceRun) -> None:
    await run.phase("A", files=False)
    await run.phase("B", files=False)
    stages = [
        ("/users/1/items/top", {"format": "versions"}),
        ("/users/1/items", {"itemKey": None}),
        ("/users/1/deleted", {}),
    ]
    for index, (path, query) in enumerate(stages, 2):
        old, new, child, pending_key = (
            f"{prefix}AAA{index}" for prefix in ("NLDA", "NEWA", "CHLD", "PNDG")
        )
        await run.phase(
            "A",
            [
                dict(action="create", key=old),
                dict(action="create", key=new),
                dict(
                    action="create",
                    key=child,
                    data=dict(itemType="note", parentItem=old, note="<p>Keep 東京</p>"),
                ),
            ],
            files=False,
        )
        await run.phase("B", [dict(action="create", key=pending_key)], files=False, sync=False)
        barrier = run.server.barrier
        barrier.arm("GET", path, "response", query=query)
        task = asyncio.create_task(run.phase("B", files=False))
        try:
            async with asyncio.timeout(60):
                await barrier.reached.wait()
            assert barrier.trace[-1]["status"] == 200
            await run.phase(
                "A",
                [
                    dict(action="json", key=child, data=dict(parentItem=new)),
                    dict(action="delete", key=old),
                ],
                files=False,
            )
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            barrier.release.set()
        right = await task
        await run.converged(await run.phase("A", files=False), right)
        items = {item["key"]: item for item in right["items"]}
        assert old not in items, "Old read resurrected a deleted parent"
        assert items[child]["parentItem"] == new, "Moved child was lost or orphaned"
        assert pending_key in items, "Graph restart lost unrelated pending work"
    await run.settled(files=False)
