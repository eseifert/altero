"""Run original ZFS transfer decisions with in-memory desktop file facades."""

import base64
import hashlib
from typing import Any

from tools.compatibility.client import ZoteroClient
from tools.compatibility.live import DesktopAPI


class DesktopStorage:
    def __init__(self, client: ZoteroClient, api: DesktopAPI) -> None:
        _, self.source = client.source("storage_download")
        self.api = api

    async def transfer(
        self,
        operation: str,
        kind: str,
        library_id: int,
        key: str,
        content: bytes,
        *,
        original: bytes | None = None,
        mtime: int = 1785701798544,
        local_mtime: int | None = None,
        synced_hash: str | None = None,
        faults: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        configuration = dict(
            source=self.source,
            operation=operation,
            kind=kind,
            libraryID=library_id,
            key=key,
            content=base64.b64encode(content).decode(),
            md5=hashlib.md5(
                original if original is not None else content, usedforsecurity=False
            ).hexdigest(),
            compressed=original is not None,
            mtime=mtime,
            localMtime=local_mtime,
            syncedHash=synced_hash,
        )
        return await self.api.call("storage", [], faults=faults, storage=configuration)
