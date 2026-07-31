"""Transparent decompression of compressed request bodies.

The desktop client gzips its full-text uploads, announcing it with
``Content-Encoding: gzip``. Without this the body reaches the JSON parser still
compressed and fails on the second byte of the gzip magic number.
"""

import gzip
import zlib

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Encodings understood on the way in.
SUPPORTED = {"gzip", "deflate"}


def _decompress(body: bytes, encoding: str) -> bytes | None:
    """Return the decompressed body, or ``None`` if it does not decompress."""
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        return zlib.decompress(body)
    except OSError, zlib.error, EOFError:
        return None


class DecompressionMiddleware:
    """Decompress a request body before anything downstream reads it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        encoding = headers.get("content-encoding", "").lower().strip()
        if encoding not in SUPPORTED:
            await self.app(scope, receive, send)
            return

        # The body has to be read whole to decompress it, so it is replayed to
        # the application as a single message.
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)

        decompressed = _decompress(body, encoding)
        if decompressed is None:
            # This middleware runs outside the exception handlers, so it answers
            # for itself rather than raising into a 500.
            response = PlainTextResponse(
                f"Request body is not valid {encoding} data", status_code=400
            )
            await response(scope, receive, send)
            return
        body = decompressed

        scope = dict(scope)
        scope["headers"] = [
            (key, value)
            for key, value in scope["headers"]
            if key.decode().lower() not in ("content-encoding", "content-length")
        ] + [(b"content-length", str(len(body)).encode())]

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
