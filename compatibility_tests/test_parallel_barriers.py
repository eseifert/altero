"""Two uploads can be held independently without replacing an armed boundary."""

import asyncio

from tools.compatibility.barriers import HTTPBarrier


async def test_two_held_requests_release_independently():
    first = HTTPBarrier()
    second = first.fork()
    first.arm("POST", "/first")
    second.arm("POST", "/second")
    committed = []

    async def app(scope, receive, send):
        committed.append(scope["path"])

    wrapped = first.wrap(app)
    tasks = [
        asyncio.create_task(wrapped(dict(type="http", method="POST", path=path), None, None))
        for path in ("/first", "/second")
    ]
    try:
        async with asyncio.timeout(2):
            await first.reached.wait()
            await second.reached.wait()
        assert not committed
        second.release.set()
        await tasks[1]
        assert committed == ["/second"]
        assert not tasks[0].done()
    finally:
        first.release.set()
        second.release.set()
        await asyncio.gather(*tasks)
    assert committed == ["/second", "/first"]
