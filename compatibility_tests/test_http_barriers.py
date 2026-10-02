"""Hold an actual response after commit while unrelated requests still proceed."""

import asyncio

from tools.compatibility.barriers import HTTPBarrier


async def test_response_barrier_holds_only_the_selected_request():
    barrier = HTTPBarrier()
    committed, sent = [], []

    async def app(scope, receive, send):
        committed.append(scope["path"])
        await send(dict(type="http.response.start", status=204))
        await send(dict(type="http.response.body", body=b""))

    async def send(message):
        sent.append(message)

    async def receive():
        return dict(type="http.request", body=b"")

    wrapped = barrier.wrap(app)
    barrier.arm("POST", "/items", "response")
    pending = asyncio.create_task(
        wrapped(dict(type="http", method="POST", path="/items"), receive, send)
    )
    try:
        async with asyncio.timeout(2):
            await barrier.reached.wait()
        assert committed == ["/items"]
        assert not sent, "Response escaped before the interrupted desktop boundary"
        await wrapped(dict(type="http", method="GET", path="/other"), receive, send)
        assert committed == ["/items", "/other"]
        assert len(sent) == 2
        # Repeated matching requests must pass rather than deadlock a retry.
        await wrapped(dict(type="http", method="POST", path="/items"), receive, send)
        assert len(sent) == 4
    finally:
        barrier.release.set()
        await pending
    assert len(sent) == 6
    assert barrier.trace[0]["status"] == 204
