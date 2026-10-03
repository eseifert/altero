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


async def test_download_barrier_preserves_bytes_and_completion():
    barrier = HTTPBarrier()
    barrier.arm("GET", "/storage/download/", "download", prefix=True)
    sent = []

    async def app(scope, receive, send):
        await send(dict(type="http.response.start", status=200))
        await send(dict(type="http.response.body", body=b"complete", more_body=False))

    async def send(message):
        sent.append(message)

    pending = asyncio.create_task(
        barrier.wrap(app)(
            dict(type="http", method="GET", path="/storage/download/token"), None, send
        )
    )
    try:
        async with asyncio.timeout(2):
            await barrier.reached.wait()
        assert sent[-1] == dict(type="http.response.body", body=b"comp", more_body=True)
        assert not pending.done()
    finally:
        barrier.release.set()
        await pending
    assert b"".join(message.get("body", b"") for message in sent) == b"complete"
    assert sent[-1]["more_body"] is False


async def test_query_barrier_does_not_catch_a_different_sync_stage():
    barrier = HTTPBarrier()
    barrier.arm("GET", "/items", query={"format": "versions", "top": "1"})
    visited = []

    async def app(scope, receive, send):
        visited.append(scope["query_string"])
        await send(dict(type="http.response.start", status=200))
        await send(dict(type="http.response.body", body=b""))

    async def send(message):
        pass

    wrapped = barrier.wrap(app)
    scope = dict(type="http", method="GET", path="/items")
    await wrapped(scope | dict(query_string=b"format=versions"), None, send)
    assert barrier.active
    assert not barrier.reached.is_set()
    pending = asyncio.create_task(
        wrapped(scope | dict(query_string=b"top=1&format=versions&since=2"), None, send)
    )
    try:
        async with asyncio.timeout(2):
            await barrier.reached.wait()
        assert visited == [b"format=versions"]
    finally:
        barrier.release.set()
        await pending


async def test_upload_barrier_stops_after_partial_body_was_consumed():
    barrier = HTTPBarrier()
    barrier.arm("POST", "/storage/upload/token", "upload")
    received = []

    async def app(scope, receive, send):
        while True:
            message = await receive()
            received.append(message["body"])
            if not message.get("more_body"):
                break

    async def receive():
        return dict(type="http.request", body=b"complete", more_body=False)

    pending = asyncio.create_task(
        barrier.wrap(app)(
            dict(type="http", method="POST", path="/storage/upload/token"), receive, None
        )
    )
    try:
        async with asyncio.timeout(2):
            await barrier.reached.wait()
        assert received == [b"comp"]
        assert not pending.done()
    finally:
        barrier.release.set()
        await pending
    assert b"".join(received) == b"complete"


async def test_runtime_inventory_keeps_protocol_headers_but_redacts_credentials():
    barrier = HTTPBarrier()

    async def app(scope, receive, send):
        await send(
            dict(
                type="http.response.start",
                status=200,
                headers=[(b"last-modified-version", b"12"), (b"set-cookie", b"secret-cookie")],
            )
        )
        await send(dict(type="http.response.body", body=b""))

    async def send(message):
        pass

    await barrier.wrap(app)(
        dict(
            type="http",
            method="GET",
            path="/keys/sessions/private-token",
            query_string=b"key=secret-key&since=3",
            headers=[(b"zotero-api-key", b"secret-key")],
        ),
        None,
        send,
    )
    trace = barrier.requests[0]
    assert trace["path"] == "/keys/sessions/{token}"
    assert trace["request_headers"] == ["zotero-api-key"]
    assert trace["response_headers"] == ["last-modified-version", "set-cookie"]
    assert trace["version"] == "12"
    assert "secret" not in str(trace)
    assert "private-token" not in str(trace)
