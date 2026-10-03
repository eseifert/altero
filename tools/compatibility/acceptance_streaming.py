"""Original desktop reconnect timers, subscriptions and notification-driven sync."""

import asyncio

from tools.compatibility.acceptance_runtime import AcceptanceRun


async def streaming_reconnect(run: AcceptanceRun) -> None:
    await run.phase("A", [dict(action="create", key="STREAM23")], files=False)
    await run.phase("B", files=False)
    ready, reconnected = run.root / "subscribed", run.root / "reconnected"
    pending = asyncio.create_task(
        run.phase(
            "B",
            [
                dict(
                    action="stream-watch",
                    url=run.server.url.replace("http:", "ws:") + "/stream",
                    ready=str(ready),
                    reconnected=str(reconnected),
                    key="STREAM23",
                    title="After reconnect 東京",
                )
            ],
            sync=False,
            files=False,
            timeout=180,
        )
    )
    try:
        async with asyncio.timeout(90):
            while not ready.exists():
                if pending.done():
                    await pending
                await asyncio.sleep(0.05)
            await run.server.barrier.disconnect_websockets()
            while not reconnected.exists():
                if pending.done():
                    await pending
                await asyncio.sleep(0.05)
        stored = (await run.request("GET", "/users/1/items/STREAM23")).json()
        await run.request(
            "POST",
            "/users/1/items",
            json=[
                dict(
                    key="STREAM23",
                    version=stored["version"],
                    title="After reconnect 東京",
                )
            ],
        )
        right = await pending
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    assert right["streaming"]["automaticSync"]
    events = run.server.barrier.websocket_events
    assert sum(e["event"] == "subscriptionsCreated" for e in events) == 2
    assert any(e["event"] == "topicUpdated" for e in events)
    await run.converged(await run.phase("A", files=False), right)
    await run.settled(files=False)
