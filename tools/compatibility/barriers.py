"""Pause one real HTTP request at a specified boundary, without changing data."""

import asyncio


class HTTPBarrier:
    def __init__(self):
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.active = False
        self.trace: list[dict] = []

    def arm(self, method: str, path: str, point="before", *, prefix=False) -> None:
        if self.active or (self.reached.is_set() and not self.release.is_set()):
            raise ValueError("An HTTP barrier is already armed")
        if point not in {"before", "response", "download"}:
            raise ValueError("Unknown HTTP barrier point")
        self.method, self.path, self.point = method, path, point
        self.prefix = prefix
        self.reached.clear()
        self.release.clear()
        self.active = True

    async def pause(self, status=None):
        self.trace.append(dict(method=self.method, path=self.path, point=self.point, status=status))
        self.reached.set()
        await self.release.wait()

    def wrap(self, app):
        async def wrapped(scope, receive, send):
            if not (
                self.active
                and scope["type"] == "http"
                and scope["method"] == self.method
                and (
                    scope["path"].startswith(self.path)
                    if self.prefix
                    else scope["path"] == self.path
                )
            ):
                return await app(scope, receive, send)
            self.active = False
            point = self.point
            if self.point == "before":
                await self.pause()

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

            await app(scope, receive, response)

        return wrapped
