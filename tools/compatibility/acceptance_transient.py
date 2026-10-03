"""Real desktop retries, uncertain commits, truncated reads and user cancellation."""

import asyncio

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def transient_errors(run: AcceptanceRun) -> None:
    await run.phase("A", files=False)
    await run.phase("B", files=False)
    barrier = run.server.barrier
    connection_error = "Error connecting to server. Check your Internet connection."
    for index, (point, fault) in enumerate(
        (("before", "status"), ("response", "status"), ("response", "disconnect"))
    ):
        key = f"FAULTAA{index + 2}"
        await run.phase("A", [dict(action="create", key=key)], files=False, sync=False)
        barrier.inject("POST", "/users/1/items", point, fault=fault, status=503)
        left = await run.phase(
            "A",
            files=False,
            timeout=180,
            expected_error_message=connection_error if fault == "disconnect" else None,
        )
        assert barrier.reached.is_set(), "Desktop never reached the injected write fault"
        if fault == "disconnect":
            assert any(item["key"] == key for item in left["items"]), (
                "Lost response discarded the uncertain object"
            )
            left = await run.phase("A", files=False)
        right = await run.phase("B", files=False)
        await run.converged(left, right)
        assert len(left["items"]) == index + 1, "Retry duplicated or lost a write"
        assert (await run.request("GET", f"/users/1/items/{key}")).json()["version"] == index + 1
    await run.phase(
        "A",
        [dict(action="edit", key="FAULTAA2", fields={"title": "After truncation"})],
        files=False,
    )
    barrier.inject("GET", "/users/1/items", "download", fault="disconnect", query={"itemKey": None})
    right = await run.phase("B", files=False, timeout=180)
    assert barrier.reached.is_set(), "Desktop never encountered the truncated object response"
    right = await run.phase("B", files=False)
    await run.converged(await run.phase("A", files=False), right)

    await run.phase("A", [dict(action="create", key="CANCEL23")], files=False, sync=False)
    signal = run.root / "cancel-sync"
    barrier.arm("POST", "/users/1/items", fault="status", status=503)
    pending = asyncio.create_task(run.phase("A", files=False, cancel_path=signal))
    try:
        async with asyncio.timeout(60):
            await barrier.reached.wait()
            signal.touch()
            while not signal.with_name(signal.name + ".ack").exists():
                await asyncio.sleep(0.05)
    except BaseException:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        raise
    finally:
        barrier.release.set()
    cancelled = await pending
    assert cancelled["unsynced"]["item"], "Cancellation lost the queued object"
    assert not any(
        item["key"] == "CANCEL23" for item in (await run.request("GET", "/users/1/items")).json()
    )
    await run.converged(await run.phase("A", files=False), await run.phase("B", files=False))
    await run.settled(files=False)
