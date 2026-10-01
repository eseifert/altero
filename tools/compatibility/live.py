"""Execute the complete original API client with asynchronous socket transport."""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tools.compatibility.client import CompatibilityError, ZoteroClient

RUNNER = Path(__file__).with_name("live_api.mjs")


class DesktopAPI:
    """A call returns its value, sanitized HTTP trace, delays and any client error."""

    def __init__(self, client: ZoteroClient, base_url: str, key: str) -> None:
        _, self.source = client.source("sync_versions")
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise CompatibilityError("Live compatibility replay requires a local HTTP server")
        self.base_url = base_url.rstrip("/") + "/"
        self.key = key

    async def call(
        self,
        method: str,
        args: list[Any],
        *,
        faults: list[dict[str, Any]] | None = None,
        storage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = dict(
            source=self.source,
            baseURL=self.base_url,
            key=self.key,
            method=method,
            args=args,
            faults=faults or [],
            storage=storage,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                "node",
                str(RUNNER),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise CompatibilityError("Cannot start the Node desktop API runner") from error
        try:
            async with asyncio.timeout(30):
                stdout, stderr = await process.communicate(json.dumps(request).encode())
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise CompatibilityError(stderr.decode().strip() or "Desktop API runner failed")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as error:
            raise CompatibilityError("Desktop API runner returned invalid JSON") from error
