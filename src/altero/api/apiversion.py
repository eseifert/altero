"""Answering only for the API version this server implements.

A client asking for v1 or v2 would expect Atom, which is not served here, so
saying so is better than returning v3 bodies under a v2 label. Every answer
names the version it is in.

Plain ASGI rather than Starlette's ``BaseHTTPMiddleware``, which relays every
response body through a memory stream and a task of its own: two of those cost
a quarter of a large download's throughput.
"""

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from altero import API_VERSION


class ApiVersionMiddleware:
    """Refuse another API version, and label every response with this one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        header = request.headers.get("Zotero-API-Version")
        parameter = request.query_params.get("v")

        if header and parameter and header != parameter:
            refusal = PlainTextResponse(
                "Zotero-API-Version header does not match 'v' query parameter",
                status_code=400,
            )
            await refusal(scope, receive, send)
            return

        requested = header or parameter
        if requested and requested != str(API_VERSION):
            refusal = PlainTextResponse(
                f"Invalid API version '{requested}'; this server implements {API_VERSION}",
                status_code=400,
            )
            await refusal(scope, receive, send)
            return

        async def labelled(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Zotero-API-Version"] = str(API_VERSION)
            await send(message)

        await self.app(scope, receive, labelled)
