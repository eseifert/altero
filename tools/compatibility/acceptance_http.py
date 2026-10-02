"""The actual desktop waits for real middleware 429s, preserving queued writes."""

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def http_policy(run: AcceptanceRun) -> None:
    await run.phase("A", files=False)
    await run.phase("B", files=False)
    await run.phase("A", [dict(action="create", key="THRTTLE2")], files=False, sync=False)
    limiter = run.server.limiter
    assert limiter is not None
    start = len(run.server.barrier.requests)
    limiter.limit, limiter.window = 1, 1
    try:
        left = await run.phase("A", files=False, timeout=180)
        right = await run.phase("B", files=False, timeout=180)
    finally:
        limiter.limit = 0
    requests = run.server.barrier.requests[start:]
    assert any(request.get("status") == 429 for request in requests), (
        "The real limiter never refused a request"
    )
    assert any(
        request.get("status") == 200 and request["method"] == "POST" for request in requests
    ), "Queued writes never settled after throttling"
    await run.converged(left, right)
    assert len(left["items"]) == 1, "Throttled retries duplicated or lost a write"
    await run.settled(files=False)
