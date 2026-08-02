"""A whole sync cycle, driven over a real socket.

Every other test in this suite reaches the application through
``httpx.ASGITransport``, which never opens a connection. Two bugs have already
survived that: an orphaned child item and an attachment template the client
could not use, both found only when a real server was driven from outside. This
replays what the desktop client actually does -- the request sequence, headers
and encodings taken from its debug log -- against uvicorn on a port, and checks
that what one client uploads is what another downloads.

The library is uploaded by one client and read back by a second one that shares
nothing with it, because convergence is the property that matters: a sync is
only correct if the next client sees exactly what the last one sent.
"""

import asyncio
import gzip
import hashlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from altero.app import create_app
from altero.settings import Settings
from tests.factories import make_api_key, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

#: How long to wait for uvicorn to bind before giving up.
STARTUP_TIMEOUT = 15.0

SNAPSHOT = b"<html><body>The Brutalist Report</body></html>"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sync.sqlite'}",
        storage_path=tmp_path / "storage",
    )


@pytest.fixture
async def server(settings: Settings) -> AsyncIterator[str]:
    """Run the real server on an ephemeral port and yield its base URL."""
    app = create_app(settings)
    await app.state.database.create_all()
    async with app.state.database.session_factory() as session:
        await make_user(session, user_id=1, username="seiferte")
        await make_api_key(session, key=KEY, user_id=1)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="error", access_log=False, lifespan="on"
    )
    running = uvicorn.Server(config)
    task = asyncio.create_task(running.serve())

    deadline = time.monotonic() + STARTUP_TIMEOUT
    while not running.started:
        if task.done():  # pragma: no cover - surfaces a startup failure
            task.result()
            raise RuntimeError("server exited before it started")
        if time.monotonic() > deadline:  # pragma: no cover - CI is not that slow
            raise TimeoutError("server did not start")
        await asyncio.sleep(0.01)

    port = running.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        running.should_exit = True
        await task


@pytest.fixture
async def uploader(server: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=server, timeout=30) as client:
        yield client


@pytest.fixture
async def downloader(server: str) -> AsyncIterator[httpx.AsyncClient]:
    """A second client, sharing nothing with the first but the server."""
    async with httpx.AsyncClient(base_url=server, timeout=30) as client:
        yield client


def gzipped(payload: object) -> tuple[bytes, dict[str, str]]:
    """Encode a body the way the client does, which is gzipped and announced."""
    body = gzip.compress(json.dumps(payload).encode())
    return body, {"Content-Type": "application/json", "Content-Encoding": "gzip"}


async def upload_items(
    client: httpx.AsyncClient, *, since: int, version: int = 0
) -> httpx.Response:
    """Send the parent and its attachment in one batch, as the client does.

    ``since`` is the library version the client believes it holds; ``version``
    is what each object claims, which is 0 for something it has never synced.
    """
    body, headers = gzipped(
        [
            {
                "key": "Z2JFGHNV",
                "version": version,
                "itemType": "webpage",
                "title": "The Brutalist Report",
                "url": "https://brutalist.report/",
                "accessDate": "2026-08-02T20:20:31Z",
                "creators": [],
                "tags": [],
                "collections": [],
                "relations": {},
                "dateAdded": "2026-08-02T20:20:31Z",
                "dateModified": "2026-08-02T20:20:31Z",
            },
            {
                "key": "BG92XXQJ",
                "version": version,
                "itemType": "attachment",
                "title": "The Brutalist Report",
                "url": "https://brutalist.report/",
                "accessDate": "2026-08-02T20:20:38Z",
                "parentItem": "Z2JFGHNV",
                "linkMode": "imported_url",
                "contentType": "text/html",
                "charset": "utf-8",
                "filename": "brutalist.report.html",
                "tags": [],
                "relations": {},
                "dateAdded": "2026-08-02T20:20:38Z",
                "dateModified": "2026-08-02T20:20:38Z",
            },
        ]
    )
    return await client.post(
        "/users/1/items",
        content=body,
        headers=AUTH | headers | {"If-Unmodified-Since-Version": str(since)},
    )


class TestASyncCycleOverASocket:
    async def test_a_library_uploaded_by_one_client_is_what_another_downloads(
        self, uploader: httpx.AsyncClient, downloader: httpx.AsyncClient, server: str
    ) -> None:
        # 1. The client checks its key before anything else.
        keys = await uploader.get("/keys/current", headers=AUTH)
        assert keys.status_code == 200
        assert keys.json()["userID"] == 1

        # 2. Then asks what has changed since the version it holds. A library
        #    nobody has written to is at 0, and 304 is the answer it expects.
        settings = await uploader.get("/users/1/settings", params={"since": 0}, headers=AUTH)
        assert settings.status_code == 200
        assert settings.headers["Last-Modified-Version"] == "0"

        # 3. It reads every object type as versions to work out the difference.
        for path, params in (
            ("/users/1/collections", {"format": "versions"}),
            ("/users/1/searches", {"format": "versions"}),
            ("/users/1/items", {"format": "versions", "includeTrashed": 1}),
        ):
            listing = await uploader.get(path, params=params, headers=AUTH)
            assert listing.status_code == 200
            assert listing.json() == {}

        # 4. Uploads the parent and the attachment together, gzipped.
        upload = await upload_items(uploader, since=0)
        assert upload.status_code == 200
        written = upload.json()["successful"]
        assert set(written) == {"0", "1"}
        # One request, one version, however many objects it carried.
        assert {obj["version"] for obj in written.values()} == {1}
        assert upload.headers["Last-Modified-Version"] == "1"

        # 5. Authorizes the file, sends it, registers it. Three requests, as
        #    the protocol has it.
        digest = hashlib.md5(SNAPSHOT, usedforsecurity=False).hexdigest()
        authorization = await uploader.post(
            "/users/1/items/BG92XXQJ/file",
            data={
                "md5": digest,
                "filename": "brutalist.report.html",
                "filesize": len(SNAPSHOT),
                "mtime": 1785701798544,
                "contentType": "text/html",
                "charset": "utf-8",
            },
            headers=AUTH | {"If-None-Match": "*"},
        )
        assert authorization.status_code == 200
        instructions = authorization.json()

        # The client hands this straight to XMLHttpRequest.open(), which
        # rejects a bare path. Only a real socket can tell the difference: the
        # ASGI transport resolves a relative URL against its base and passes.
        assert instructions["url"].startswith(server)

        sent = await uploader.post(instructions["url"], content=SNAPSHOT, headers=AUTH)
        assert sent.status_code == 201

        registered = await uploader.post(
            "/users/1/items/BG92XXQJ/file",
            data={"upload": instructions["uploadKey"]},
            headers=AUTH,
        )
        assert registered.status_code == 204

        # 6. And uploads the extracted text in the batch form the client uses.
        body, headers = gzipped(
            [
                {
                    "key": "BG92XXQJ",
                    "content": "The Brutalist Report",
                    "indexedChars": 20,
                    "totalChars": 20,
                    "indexedPages": 0,
                    "totalPages": 0,
                }
            ]
        )
        fulltext = await uploader.post(
            "/users/1/fulltext",
            content=body,
            headers=AUTH
            | headers
            | {"If-Unmodified-Since-Version": registered.headers["Last-Modified-Version"]},
        )
        assert fulltext.status_code == 200

        # The second client now reads the library from scratch.
        versions = await downloader.get(
            "/users/1/items", params={"format": "versions", "includeTrashed": 1}, headers=AUTH
        )
        assert set(versions.json()) == {"Z2JFGHNV", "BG92XXQJ"}

        attachment = (await downloader.get("/users/1/items/BG92XXQJ", headers=AUTH)).json()
        # The child kept its parent: an orphan here is the bug that a green
        # suite missed once already.
        assert attachment["data"]["parentItem"] == "Z2JFGHNV"
        assert attachment["data"]["filename"] == "brutalist.report.html"
        assert attachment["data"]["md5"] == digest

        parent = (await downloader.get("/users/1/items/Z2JFGHNV", headers=AUTH)).json()
        assert parent["meta"]["numChildren"] == 1

        downloaded = await downloader.get("/users/1/items/BG92XXQJ/file", headers=AUTH)
        assert downloaded.status_code == 200
        assert downloaded.content == SNAPSHOT

        text = await downloader.get("/users/1/items/BG92XXQJ/fulltext", headers=AUTH)
        assert text.json()["content"] == "The Brutalist Report"

    async def test_a_rolled_back_client_resending_version_zero_is_told_to_reconcile(
        self, uploader: httpx.AsyncClient
    ) -> None:
        """The shape the stuck client took: the same batch, over and over.

        A client whose upload transaction rolled back still believes its objects
        are new, so it re-sends them claiming version 0 while the server holds
        them at 1. Each is a per-object 412, which is what tells the client to
        stop and reconcile -- the real one answers by resetting the library and
        downloading. Reporting them as written would hand back versions it
        cannot use; reporting them unchanged would leave it believing an upload
        succeeded that never happened.
        """
        first = await upload_items(uploader, since=0)
        assert set(first.json()["successful"]) == {"0", "1"}

        again = await upload_items(uploader, since=1)

        assert again.status_code == 200
        report = again.json()
        assert report["successful"] == {}
        assert report["unchanged"] == {}
        assert {entry["code"] for entry in report["failed"].values()} == {412}
        assert report["failed"]["0"]["key"] == "Z2JFGHNV"
        # Nothing was written, so nothing may consume a version: a library that
        # climbs on a rejected batch makes every other client re-download.
        assert again.headers["Last-Modified-Version"] == "1"

    async def test_resending_an_identical_object_costs_nothing(
        self, uploader: httpx.AsyncClient
    ) -> None:
        """A client re-sending what it correctly holds is told nothing changed.

        Both objects come back under ``unchanged`` and the library stays where
        it was, so no other client is made to re-download anything. Writing them
        again would be visible library-wide for no reason.
        """
        await upload_items(uploader, since=0)

        again = await upload_items(uploader, since=1, version=1)

        assert again.json()["successful"] == {}
        assert set(again.json()["unchanged"]) == {"0", "1"}
        assert again.headers["Last-Modified-Version"] == "1"
