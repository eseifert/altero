"""Pause one real HTTP request at a specified boundary, without changing data."""

import asyncio
from urllib.parse import parse_qs


class HTTPBarrier:
    def __init__(self):
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.active = False
        self.trace: list[dict] = []
        self.requests: list[dict] = []

    def arm(self, method: str, path: str, point="before", *, prefix=False, query=None) -> None:
        if self.active or (self.reached.is_set() and not self.release.is_set()):
            raise ValueError("An HTTP barrier is already armed")
        if point not in {"before", "response", "download", "upload"}:
            raise ValueError("Unknown HTTP barrier point")
        self.method, self.path, self.point = method, path, point
        self.prefix = prefix
        self.query = query or {}
        self.reached.clear()
        self.release.clear()
        self.active = True
        self.upload_boundary: dict = {}

    async def pause(self, status=None):
        self.trace.append(
            dict(
                method=self.method,
                path=self.path,
                point=self.point,
                status=status,
                **self.upload_boundary,
            )
        )
        self.reached.set()
        await self.release.wait()

    def wrap(self, app):
        async def wrapped(scope, receive, send):
            if scope["type"] != "http":
                return await app(scope, receive, send)
            query = parse_qs(scope.get("query_string", b"").decode())
            # Only protocol selectors are retained; credentials never enter the trace.
            entry = dict(
                method=scope["method"],
                path=scope["path"],
                query={
                    key: value
                    for key, value in query.items()
                    if key in {"format", "since", "top", "itemKey"}
                },
            )
            self.requests.append(entry)
            original_send = send

            async def traced_send(message):
                if message["type"] == "http.response.start":
                    entry["status"] = message["status"]
                await original_send(message)

            send = traced_send
            if not (
                self.active
                and scope["type"] == "http"
                and scope["method"] == self.method
                and (
                    scope["path"].startswith(self.path)
                    if self.prefix
                    else scope["path"] == self.path
                )
                and all(
                    query.get(key) if value is None else query.get(key) == [value]
                    for key, value in self.query.items()
                )
            ):
                return await app(scope, receive, send)
            self.active = False
            point = self.point
            if self.point == "before":
                await self.pause()

            remainder = None
            original_receive = receive

            async def upload_receive():
                nonlocal remainder, point
                if remainder is not None:
                    await self.pause()
                    message, remainder = remainder, None
                    point = "done"
                    return message
                message = await original_receive()
                if point == "upload" and message["type"] == "http.request" and message.get("body"):
                    body = message["body"]
                    middle = max(1, len(body) // 2)
                    self.upload_boundary = dict(
                        consumed_bytes=middle, more_body=message.get("more_body", False)
                    )
                    remainder = message | dict(body=body[middle:])
                    return message | dict(body=body[:middle], more_body=True)
                return message

            async def response(message):
                nonlocal point
                if point == "response" and message["type"] == "http.response.start":
                    await self.pause(message["status"])
                if (
                    point == "download"
                    and message["type"] == "http.response.body"
                    and message.get("body")
                ):
                    body = message["body"]
                    middle = max(1, len(body) // 2)
                    await send(message | dict(body=body[:middle], more_body=True))
                    await self.pause()
                    point = "done"
                    message = message | dict(body=body[middle:])
                await send(message)

            await app(scope, upload_receive if point == "upload" else receive, response)

        return wrapped
