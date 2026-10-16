"""Transparent decompression of compressed request bodies.

The desktop client gzips its full-text uploads, announcing it with
``Content-Encoding: gzip``. Without this the body reaches the JSON parser still
compressed and fails on the second byte of the gzip magic number.

This runs before anybody is authenticated, so what it reads and what it inflates
are both bounded: a few hundred kilobytes of gzip would otherwise become
gigabytes in memory at the request of anybody who can reach the port.
"""

import asyncio
import zlib

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Encodings understood on the way in.
SUPPORTED = {"gzip", "deflate"}

#: The most a compressed body may hold, and the most it may inflate to. The
#: client compresses every write of any size, and the largest it can send is a
#: batch of 50 notes at upstream's 500,000 characters each -- about 100 MB at
#: four bytes a character. Read at call time, so a test can lower it.
MAX_BODY_BYTES = 128 * 1024 * 1024

#: ``wbits`` for a gzip stream; plain zlib's default reads ``deflate``.
_WBITS = {"gzip": 16 + zlib.MAX_WBITS, "deflate": zlib.MAX_WBITS}


class _TooLarge(Exception):
    """The body inflates past :data:`MAX_BODY_BYTES`."""


def _decompress(body: bytes, encoding: str, limit: int) -> bytes | None:
    """Return the decompressed body, or ``None`` if it does not decompress.

    Raises:
        _TooLarge: If the body inflates to more than ``limit`` bytes. It stops
            there rather than inflating the rest to find out how much more.
    """
    if not body and encoding == "gzip":
        return b""  # as `gzip.decompress` reads it

    chunks: list[bytes] = []
    size = 0
    remaining = body
    try:
        while True:
            decompressor = zlib.decompressobj(_WBITS[encoding])
            # One byte past the limit is enough to know it was passed.
            chunk = decompressor.decompress(remaining, limit - size + 1)
            size += len(chunk)
            if size > limit:
                raise _TooLarge
            chunks.append(chunk)
            if not decompressor.eof:
                return None  # truncated
            # What `gzip.decompress` and `zlib.decompress` accept, these accept:
            # concatenated gzip members are one stream and zero bytes after one
            # are padding, while whatever follows a zlib stream is ignored.
            remaining = decompressor.unused_data.lstrip(b"\0")
            if not remaining or encoding != "gzip":
                break
    except zlib.error:
        return None
    return b"".join(chunks)


async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, text: str) -> None:
    """Answer for ourselves: this runs outside the exception handlers."""
    await PlainTextResponse(text, status_code=status)(scope, receive, send)


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

        limit = MAX_BODY_BYTES
        too_large = f"Request body is larger than {limit} bytes"
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            await _refuse(scope, receive, send, 413, too_large)
            return

        # The body has to be read whole to decompress it, so it is replayed to
        # the application as a single message.
        chunks: list[bytes] = []
        received = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > limit:
                await _refuse(scope, receive, send, 413, too_large)
                return
            chunks.append(chunk)
            more = message.get("more_body", False)

        try:
            # Off the event loop: inflating a large body takes long enough to
            # hold up every other request this process is serving.
            body = await asyncio.to_thread(_decompress, b"".join(chunks), encoding, limit)
        except _TooLarge:
            await _refuse(scope, receive, send, 413, too_large)
            return
        if body is None:
            await _refuse(scope, receive, send, 400, f"Request body is not valid {encoding} data")
            return

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
