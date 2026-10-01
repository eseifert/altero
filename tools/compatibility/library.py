"""Call original desktop API methods for one library."""

from dataclasses import dataclass
from typing import Any

from tools.compatibility.live import DesktopAPI


@dataclass
class LibraryReplay:
    api: DesktopAPI
    kind: str
    id: int

    @property
    def prefix(self) -> str:
        return f"/{self.kind}s/{self.id}"

    async def call(self, method: str, *args: Any, **options: Any) -> dict[str, Any]:
        return await self.api.call(method, [self.kind, self.id, *args], **options)

    async def value(self, method: str, *args: Any) -> Any:
        result = await self.call(method, *args)
        assert result["error"] is None, result
        return result["value"]

    async def upload(self, objects: list[dict[str, Any]], version: int = 0, kind="item") -> Any:
        result = await self.value("uploadObjects", "POST", version, kind, objects)
        assert not result["results"]["failed"], result
        return result
