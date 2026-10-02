"""Compare actual desktop persistence with the server after explicit phases."""

import json
from pathlib import Path

import httpx

from tools.compatibility.desktop import prepare_profile, run_phase
from tools.compatibility.runtime import TestServer


class AcceptanceRun:
    def __init__(self, executable: Path, version: str, root: Path, server: TestServer):
        self.executable, self.version, self.root, self.server = executable, version, root, server
        self.phases: list[dict] = []
        for name in ("A", "B"):
            prepare_profile(root / name, server.url)

    async def phase(self, name: str, operations=(), **options) -> dict:
        snapshot = await run_phase(
            self.executable,
            self.root / name,
            version=self.version,
            key=options.pop("key", self.server.key),
            operations=list(operations),
            **options,
        )
        path = self.root / f"phase-{len(self.phases) + 1}-{name}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        self.phases.append(dict(client=name, operations=list(operations), snapshot=path.name))
        return snapshot

    async def request(self, method: str, path: str, *, key=None, **options) -> httpx.Response:
        async with httpx.AsyncClient(base_url=self.server.url) as client:
            response = await client.request(
                method,
                path,
                headers={"Zotero-API-Key": key or self.server.key, "Zotero-API-Version": "3"},
                **options,
            )
        response.raise_for_status()
        return response

    async def converged(self, left: dict, right: dict, prefix="/users/1") -> None:
        """Check every object and unsynced queue, not just matching screen titles."""

        def by_key(values):
            return {
                value["key"]: {
                    field: sorted(content) if field == "collections" else content
                    for field, content in value.items()
                    if field in {"key", "version"} or content not in (None, "", [], {}, False)
                }
                for value in values
            }

        for kind in ("items", "collections", "searches"):
            expected = by_key(left[kind])
            assert expected == by_key(right[kind]), f"Desktop {kind} differ"
            response = await self.request(
                "GET", f"{prefix}/{kind}", params={"limit": 100, "includeTrashed": 1}
            )
            assert expected == by_key([value["data"] for value in response.json()]), (
                f"Server {kind} differ from desktop persistence"
            )
        for snapshot in (left, right):
            assert not any(snapshot["unsynced"].values()), "Desktop still has unsynced objects"
        assert left["files"] == right["files"], "Persisted attachment bytes differ"
