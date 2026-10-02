"""Change the actual server graph while a desktop is consuming an older response."""

import asyncio

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def read_races(run: AcceptanceRun) -> None:
    await run.phase(
        "A",
        [dict(action="create", key="RACE2345"), dict(action="create", key="TARGET23")],
        files=False,
    )
    await run.phase("B", files=False)
    stages = (
        ("settings", "/users/1/settings", {}),
        ("top-versions", "/users/1/items/top", {"format": "versions"}),
        ("objects", "/users/1/items", {"itemKey": None}),
        ("deletions", "/users/1/deleted", {}),
    )
    for number, (stage, path, query) in enumerate(stages):
        # Force a download and preserve a disjoint local change through every restart.
        await run.phase(
            "A",
            [dict(action="edit", key="RACE2345", fields={"title": f"before {stage}"})],
            files=False,
        )
        pending_key = f"PNDRAAA{number + 2}"
        await run.phase("B", [dict(action="create", key=pending_key)], files=False, sync=False)
        barrier = run.server.barrier
        start = len(barrier.requests)
        barrier.arm("GET", path, "response", query=query)
        task = asyncio.create_task(run.phase("B", files=False))
        try:
            async with asyncio.timeout(60):
                await barrier.reached.wait()
            assert barrier.trace[-1]["status"] == 200, f"{stage} did not hold a successful response"
            before_concurrent = len(barrier.requests)
            await run.phase(
                "A",
                [dict(action="edit", key="RACE2345", fields={"title": f"after {stage}"})],
                files=False,
            )
            after_concurrent = len(barrier.requests)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            barrier.release.set()
        right = await task
        desktop_reads = (
            barrier.requests[start:before_concurrent] + barrier.requests[after_concurrent:]
        )
        left = await run.phase("A", files=False)
        await run.converged(left, right)
        state = {item["key"]: item for item in right["items"]}
        assert state["RACE2345"]["title"] == f"after {stage}", (
            "Desktop advanced past an unseen edit"
        )
        assert pending_key in state, "Download restart lost pending work"
        if stage != "deletions":
            settings_reads = [
                request
                for request in desktop_reads
                if request["method"] == "GET" and request["path"] == "/users/1/settings"
            ]
            assert len(settings_reads) >= 2, (
                "A changed watermark did not restart the download cycle"
            )
    await run.settled(files=False)
