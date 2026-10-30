"""Compare actual desktop persistence with the server after explicit phases."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from sqlalchemy import select

from altero.models import Library, User
from altero.services import websessions
from tools.compatibility.desktop import prepare_profile, run_phase
from tools.compatibility.runtime import TestServer


class AcceptanceRun:
    def __init__(self, executable: Path, version: str, root: Path, server: TestServer):
        root = root.resolve()
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

    async def request(self, method: str, path: str, *, key=None, **options) -> httpx2.Response:
        async with httpx2.AsyncClient(base_url=self.server.url) as client:
            response = await client.request(
                method,
                path,
                headers={"Zotero-API-Key": key or self.server.key, "Zotero-API-Version": "3"},
                **options,
            )
        response.raise_for_status()
        return response

    @asynccontextmanager
    async def browser(self) -> AsyncIterator[httpx2.AsyncClient]:
        """The web interface signed in as the desktops' user, on their personal library.

        Its routes are relative to `/web/libraries/<id>`; the cookie and the
        CSRF token are those a page holds after signing in.
        """
        assert self.server.session_factory is not None
        async with self.server.session_factory() as session:
            user = await session.get(User, 1)
            assert user is not None
            token, _ = await websessions.create(session, user)
            library = await session.scalar(select(Library).where(Library.owner_id == 1))
            assert library is not None
            library_id = library.id
        async with httpx2.AsyncClient(
            base_url=f"{self.server.url}/web/libraries/{library_id}",
            cookies={"altero_session": token, "altero_csrf": "acceptance-csrf"},
            headers={"X-CSRF-Token": "acceptance-csrf"},
        ) as client:
            yield client

    async def converged(self, left: dict, right: dict, prefix="/users/1") -> None:
        """Check every object and unsynced queue, not just matching screen titles."""

        def by_key(values):
            def normalize(field, content):
                if field == "lastRead":
                    return int(content or 0)
                if field == "collections":
                    return sorted(content)
                if field == "tags":
                    return sorted(
                        ({"tag": tag["tag"], "type": tag.get("type", 0)} for tag in content),
                        key=lambda tag: (tag["tag"], tag["type"]),
                    )
                if field == "relations":
                    return {
                        name: sorted(value if isinstance(value, list) else [value])
                        for name, value in content.items()
                    }
                return content

            return {
                value["key"]: {
                    field: normalize(field, content)
                    for field, content in value.items()
                    if field != "version"
                    and (field == "key" or content not in (None, "", [], {}, False))
                }
                for value in values
            }

        for kind in ("items", "collections", "searches"):
            expected = by_key(left[kind])
            assert expected == by_key(right[kind]), f"Desktop {kind} differ"
            values = []
            while True:
                response = await self.request(
                    "GET",
                    f"{prefix}/{kind}",
                    params={"limit": 100, "start": len(values), "includeTrashed": 1},
                )
                page = response.json()
                values.extend(value["data"] for value in page)
                if len(page) < 100:
                    break
            assert expected == by_key(values), f"Server {kind} differ from desktop persistence"
            # The original engine stamps successful and unchanged objects with
            # the batch watermark. It explicitly allows local versions above
            # an unchanged object's actual server version (syncEngine.js).
            versions = {value["key"]: value["version"] for value in values}
            for snapshot in (left, right):
                for value in snapshot[kind]:
                    assert 0 < versions[value["key"]] <= value["version"], (
                        f"Desktop {kind} version is behind the server"
                    )
        for snapshot in (left, right):
            assert not any(snapshot["unsynced"].values()), "Desktop still has unsynced objects"
        assert left["files"] == right["files"], "Persisted attachment bytes differ"
        if "settings" in left or "settings" in right:
            stored = (await self.request("GET", f"{prefix}/settings")).json()
            expected = {key: value["value"] for key, value in stored.items()}
            for snapshot in (left, right):
                assert {
                    key: value["value"] for key, value in snapshot["settings"].items()
                } == expected, "Desktop settings differ from server persistence"
                for key, value in stored.items():
                    # SyncedSettings.set returns early for an equal primitive,
                    # so even a later remote version can leave local metadata older.
                    assert value["version"] > 0, "Server setting version is invalid"
                    assert snapshot["settings"][key]["version"] > 0, (
                        "Desktop setting was never synced"
                    )

    async def settled(self, *, prefix="/users/1", **options) -> None:
        """A further real sync must preserve state and the server watermark."""
        path = f"{prefix}/items?format=versions"
        before = (await self.request("GET", path)).headers["Last-Modified-Version"]
        left, right = await self.phase("A", **options), await self.phase("B", **options)
        await self.converged(left, right, prefix)
        after = (await self.request("GET", path)).headers["Last-Modified-Version"]
        assert before == after, "Settled desktops keep changing the library"
