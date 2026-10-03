"""Pause one real HTTP request at a specified boundary, without changing data."""

import asyncio
import re
from urllib.parse import parse_qs


class HTTPBarrier:
    def __init__(self):
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.active = False
        self.trace: list[dict] = []
        self.requests: list[dict] = []

    def arm(
        self,
        method: str,
        path: str,
        point="before",
        *,
        prefix=False,
        query=None,
        fault=None,
        status=503,
    ) -> None:
        if self.active or (self.reached.is_set() and not self.release.is_set()):
            raise ValueError("An HTTP barrier is already armed")
        if point not in {"before", "response", "download", "upload"}:
            raise ValueError("Unknown HTTP barrier point")
        if fault not in {None, "status", "disconnect"}:
            raise ValueError("Unknown HTTP fault")
        if fault == "status" and (point not in {"before", "response"} or not 400 <= status <= 599):
            raise ValueError("Status faults require an error code at a request/response boundary")
        self.fault, self.fault_status = fault, status
        self.method, self.path, self.point = method, path, point
        self.prefix = prefix
        self.query = query or {}
        self.reached.clear()
        self.release.clear()
        self.active = True
        self.upload_boundary: dict = {}

    def inject(self, method, path, point="before", **options) -> None:
        """A one-shot fault without a coordinating pause; the next request runs intact."""
        if not options.get("fault"):
            raise ValueError("An injected boundary needs a fault")
        self.arm(method, path, point, **options)
        self.release.set()

    async def pause(self, status=None):
        self.trace.append(
            dict(
                method=self.method,
                path=self.path,
                point=self.point,
                status=status,
                fault=self.fault,
                fault_status=self.fault_status if self.fault == "status" else None,
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
                path=re.sub(
                    r"(/(?:keys/sessions|storage/(?:upload|download))/)[^/]+",
                    r"\1{token}",
                    scope["path"],
                ),
                request_headers=sorted(
                    {name.decode("latin-1").lower() for name, _ in scope.get("headers", [])}
                ),
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
                    headers = {
                        name.decode("latin-1").lower(): value.decode("latin-1")
                        for name, value in message.get("headers", [])
                    }
                    entry["response_headers"] = sorted(headers)
                    if "last-modified-version" in headers:
                        entry["version"] = headers["last-modified-version"]
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
            fault, fault_status = self.fault, self.fault_status

            async def refusal():
                await send(
                    dict(
                        type="http.response.start",
                        status=fault_status,
                        headers=[(b"content-length", b"0")],
                    )
                )
                await send(dict(type="http.response.body", body=b""))

            if self.point == "before":
                await self.pause()
                if fault == "status":
                    return await refusal()
                if fault == "disconnect":
                    await send(
                        dict(
                            type="http.response.start",
                            status=200,
                            headers=[(b"content-length", b"1")],
                        )
                    )
                    raise ConnectionResetError("Injected interruption before request execution")

            remainder = None
            original_receive = receive

            async def upload_receive():
                nonlocal remainder, point
                if remainder is not None:
                    await self.pause()
                    if fault == "disconnect":
                        point = "done"
                        return dict(type="http.disconnect")
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

            replaced = False

            async def response(message):
                nonlocal point, replaced
                if replaced:
                    return
                if point == "response" and message["type"] == "http.response.start":
                    await self.pause(message["status"])
                    if fault == "status":
                        replaced = True
                        return await refusal()
                    if fault == "disconnect":
                        await send(message)
                        raise ConnectionResetError("Injected interruption after request execution")
                if (
                    point == "download"
                    and message["type"] == "http.response.body"
                    and message.get("body")
                ):
                    body = message["body"]
                    middle = max(1, len(body) // 2)
                    await send(message | dict(body=body[:middle], more_body=True))
                    await self.pause()
                    if fault == "disconnect":
                        raise ConnectionResetError("Injected truncated response body")
                    point = "done"
                    message = message | dict(body=body[middle:])
                await send(message)

            await app(scope, upload_receive if point == "upload" else receive, response)

        return wrapped
