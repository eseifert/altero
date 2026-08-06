"""Copying a personal library in from zotero.org.

The library being read from is **another altero**, reached over an in-process
transport. That is not a shortcut: altero serves version 3 of the same API, so
the fixture is a real implementation of the thing being read rather than a set
of hand-written responses that agree with whatever the fetcher expects. What
zotero.org does and altero does not -- throttling, a file it will not serve --
is covered separately against a transport that does only that.
"""

import json
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.errors import InvalidInputError
from altero.models import LibraryType
from altero.services import admin, transfer
from altero.services.auth import get_library
from altero.services.zoteroapi import ZoteroApi, ZoteroApiError
from altero.services.zoteroimport import fetch_archive
from altero.settings import Settings
from tests import factories

SOURCE_KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": SOURCE_KEY}
JSON = AUTH | {"Content-Type": "application/json"}


@pytest.fixture
async def source(tmp_path: Path) -> AsyncIterator[FastAPI]:
    """A second server, standing in for api.zotero.org."""
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'source.sqlite'}",
        storage_path=tmp_path / "source-storage",
    )
    application = create_app(settings)
    await application.state.database.create_all()

    async with application.state.database.session_factory() as session:
        # User 4711 there, to keep the two servers' numbering apart: the whole
        # point of the rewriting is that they need not agree.
        await factories.make_user(session, user_id=4711, username="ada")
        await factories.make_api_key(session, key=SOURCE_KEY, user_id=4711, name="migration")
        await session.commit()

    yield application
    await application.state.database.dispose()


@pytest.fixture
async def remote(source: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client pointed at that server, as the fetcher will be."""
    transport = httpx.ASGITransport(app=source)
    async with httpx.AsyncClient(transport=transport) as client:
        yield client


@pytest.fixture
async def zotero(source: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client used to *fill* the source, over its own v3 API."""
    transport = httpx.ASGITransport(app=source)
    async with httpx.AsyncClient(transport=transport, base_url="http://zotero.test") as client:
        yield client


def api(remote: httpx.AsyncClient) -> ZoteroApi:
    return ZoteroApi(key=SOURCE_KEY, client=remote, base_url="http://zotero.test")


async def seed(zotero: httpx.AsyncClient, items: list[dict]) -> httpx.Response:
    response = await zotero.post("/users/4711/items", headers=JSON, json=items)
    assert response.status_code == 200, response.text
    return response


def documents(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        return {name: json.loads(bundle.read(name)) for name in bundle.namelist() if name != ""}


class TestReadingALibrary:
    async def test_the_items_come_across_with_their_keys_and_versions(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        body = (
            await seed(
                zotero,
                [
                    {"itemType": "book", "title": "Moby-Dick", "key": "AAAA2345"},
                    {"itemType": "book", "title": "Ulysses", "key": "BBBB2345"},
                ],
            )
        ).json()
        version = body["successful"]["0"]["version"]

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.items == 2
        items = documents(tmp_path / "out.zip")["items.json"]
        assert {entry["key"] for entry in items} == {"AAAA2345", "BBBB2345"}
        assert all(entry["version"] == version for entry in items)

    async def test_the_library_version_comes_across(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """What makes the copy a copy: a client is in step with it, not ahead."""
        await seed(zotero, [{"itemType": "book", "title": "Moby-Dick"}])

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.library_version >= 1
        with zipfile.ZipFile(tmp_path / "out.zip") as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["library"]["version"] == summary.library_version

    async def test_collections_keep_their_shape_and_their_items(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await zotero.post(
            "/users/4711/collections",
            headers=JSON,
            json=[{"name": "Whales", "key": "CCCC2345"}],
        )
        await zotero.post(
            "/users/4711/collections",
            headers=JSON,
            json=[{"name": "Humpbacks", "key": "DDDD2345", "parentCollection": "CCCC2345"}],
        )
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "collections": ["CCCC2345"],
                }
            ],
        )

        await fetch_archive(api(remote), destination=tmp_path / "out.zip", target_user_id=4711)

        collections = documents(tmp_path / "out.zip")["collections.json"]
        by_key = {entry["key"]: entry for entry in collections}
        assert by_key["CCCC2345"]["items"] == ["AAAA2345"]
        assert by_key["DDDD2345"]["parent"] == "CCCC2345"

    async def test_tags_carry_their_items_and_their_type(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "tags": [{"tag": "fiction"}, {"tag": "scanned", "type": 1}],
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        tags = documents(tmp_path / "out.zip")["tags.json"]
        assert summary.tags == 2
        assert {(entry["name"], entry["type"]) for entry in tags} == {
            ("fiction", 0),
            ("scanned", 1),
        }
        assert all(entry["items"] == ["AAAA2345"] for entry in tags)

    async def test_trashed_items_come_too(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """A copy that quietly emptied the trash would not be a copy."""
        await seed(
            zotero,
            [{"itemType": "book", "title": "Discarded", "key": "AAAA2345", "deleted": True}],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.items == 1
        items = documents(tmp_path / "out.zip")["items.json"]
        assert items[0]["deleted"] is True

    async def test_child_notes_name_their_parent(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await seed(zotero, [{"itemType": "book", "title": "Moby-Dick", "key": "AAAA2345"}])
        await seed(
            zotero,
            [
                {
                    "itemType": "note",
                    "note": "<p>A note</p>",
                    "key": "BBBB2345",
                    "parentItem": "AAAA2345",
                }
            ],
        )

        await fetch_archive(api(remote), destination=tmp_path / "out.zip", target_user_id=4711)

        items = documents(tmp_path / "out.zip")["items.json"]
        note = next(entry for entry in items if entry["key"] == "BBBB2345")
        assert note["parent"] == "AAAA2345"
        assert {"field": "note", "value": "<p>A note</p>"} in note["fields"]

    async def test_saved_searches_keep_their_conditions(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await zotero.post(
            "/users/4711/searches",
            headers=JSON,
            json=[
                {
                    "name": "Whales",
                    "key": "EEEE2345",
                    "conditions": [
                        {"condition": "title", "operator": "contains", "value": "whale"}
                    ],
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        searches = documents(tmp_path / "out.zip")["searches.json"]
        assert summary.searches == 1
        assert searches[0]["conditions"][0]["value"] == "whale"

    async def test_settings_come_across(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await zotero.put(
            "/users/4711/settings/tagColors",
            headers=JSON,
            json={"value": [{"name": "unread", "color": "#FF6666"}]},
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        settings = documents(tmp_path / "out.zip")["settings.json"]
        assert summary.settings == 1
        assert json.loads(settings[0]["value"]) == [{"name": "unread", "color": "#FF6666"}]

    async def test_the_deletion_log_comes_across(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await seed(zotero, [{"itemType": "book", "title": "Gone", "key": "AAAA2345"}])
        await zotero.delete(
            "/users/4711/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "1"}
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        deleted = documents(tmp_path / "out.zip")["deleted.json"]
        assert summary.deleted == 1
        assert deleted[0] == {
            "objectType": "item",
            "key": "AAAA2345",
            "version": summary.library_version,
            "deleted": deleted[0]["deleted"],
        }


class TestObjectReferences:
    """Relation URIs name an account by number, and the numbers differ."""

    async def test_a_related_item_is_pointed_at_the_new_account(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "relations": {"dc:relation": "http://zotero.org/users/4711/items/BBBB2345"},
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=9
        )

        items = documents(tmp_path / "out.zip")["items.json"]
        assert items[0]["relations"] == [
            {"predicate": "dc:relation", "object": "http://zotero.org/users/9/items/BBBB2345"}
        ]
        assert summary.rewritten == 1

    async def test_the_namespace_is_left_alone(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """`Zotero.URI` is anchored to the literal `http://zotero.org/`.

        A URI naming this server instead would stop matching in the client, and
        related items, merge tracking and `owl:sameAs` would go with it.
        """
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "relations": {"dc:relation": "http://zotero.org/users/4711/items/BBBB2345"},
                }
            ],
        )

        await fetch_archive(api(remote), destination=tmp_path / "out.zip", target_user_id=9)

        items = documents(tmp_path / "out.zip")["items.json"]
        assert items[0]["relations"][0]["object"].startswith("http://zotero.org/")

    async def test_a_group_reference_is_left_where_it_points(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """Groups are not migrated, so aiming it at a local group would lie."""
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "relations": {"owl:sameAs": "http://zotero.org/groups/77/items/BBBB2345"},
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=9
        )

        items = documents(tmp_path / "out.zip")["items.json"]
        assert items[0]["relations"][0]["object"] == "http://zotero.org/groups/77/items/BBBB2345"
        assert summary.rewritten == 0

    async def test_nothing_is_rewritten_when_the_numbers_agree(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "relations": {"dc:relation": "http://zotero.org/users/4711/items/BBBB2345"},
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.rewritten == 0


class TestAttachments:
    async def test_the_bytes_come_across(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        from altero.services.storage import file_digest

        body = b"%PDF-1.4 a very short paper"
        digest = file_digest(body)
        # Without a digest of its own: the file protocol is what puts one on
        # it, exactly as the desktop client would.
        await seed(
            zotero,
            [
                {
                    "itemType": "attachment",
                    "linkMode": "imported_file",
                    "title": "Paper",
                    "key": "AAAA2345",
                    "filename": "paper.pdf",
                    "contentType": "application/pdf",
                }
            ],
        )
        await _store(zotero, "AAAA2345", body)

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.files == 1
        assert summary.files_missing == []
        with zipfile.ZipFile(tmp_path / "out.zip") as bundle:
            assert bundle.read(f"files/{digest}") == body

    async def test_an_attachment_with_no_file_is_named_rather_than_fatal(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """The ordinary case for an account that ran out of storage."""
        await seed(
            zotero,
            [
                {
                    "itemType": "attachment",
                    "linkMode": "imported_file",
                    "title": "Paper",
                    "key": "AAAA2345",
                    "filename": "paper.pdf",
                    "md5": "d41d8cd98f00b204e9800998ecf8427e",
                    "mtime": 1700000000000,
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.files == 0
        assert summary.files_missing == ["AAAA2345"]
        assert summary.items == 1

    async def test_a_linked_file_is_not_asked_for(
        self, remote: httpx.AsyncClient, zotero: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """Its bytes were never uploaded, so asking is a wasted 404."""
        await seed(
            zotero,
            [
                {
                    "itemType": "attachment",
                    "linkMode": "linked_url",
                    "title": "A page",
                    "key": "AAAA2345",
                    "url": "https://example.org/",
                }
            ],
        )

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=4711
        )

        assert summary.files_missing == []


async def _store(zotero: httpx.AsyncClient, key: str, body: bytes) -> None:
    """Upload a file to the source server through its own file protocol."""
    from altero.services.storage import file_digest

    version = (await zotero.get(f"/users/4711/items/{key}", headers=AUTH)).json()["version"]
    headers = AUTH | {
        "If-Unmodified-Since-Version": str(version),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    authorised = await zotero.post(
        f"/users/4711/items/{key}/file",
        headers=headers | {"If-None-Match": "*"},
        data={
            "md5": file_digest(body),
            "filename": "paper.pdf",
            "filesize": str(len(body)),
            "mtime": "1700000000000",
        },
    )
    assert authorised.status_code == 200, authorised.text
    payload = authorised.json()
    if payload.get("exists"):
        return

    upload = await zotero.post(
        payload["url"],
        content=body,
        headers={"Content-Type": payload.get("contentType", "application/octet-stream")},
    )
    assert upload.status_code in (200, 201, 204), upload.text
    registered = await zotero.post(
        f"/users/4711/items/{key}/file",
        headers=headers | {"If-None-Match": "*"},
        data={"upload": payload["uploadKey"]},
    )
    assert registered.status_code == 204, registered.text


class TestWhatItRefuses:
    async def test_a_key_that_cannot_read_the_library_is_refused(
        self, source: FastAPI, remote: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        async with source.state.database.session_factory() as session:
            await factories.make_api_key(
                session, key="X" * 24, user_id=4711, name="write-only", library_read=False
            )
            await session.commit()

        narrow = ZoteroApi(key="X" * 24, client=remote, base_url="http://zotero.test")

        with pytest.raises(InvalidInputError):
            await fetch_archive(narrow, destination=tmp_path / "out.zip", target_user_id=1)

    async def test_an_unknown_key_is_refused(
        self, remote: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        wrong = ZoteroApi(key="Z" * 24, client=remote, base_url="http://zotero.test")

        with pytest.raises(InvalidInputError):
            await fetch_archive(wrong, destination=tmp_path / "out.zip", target_user_id=1)


class TestRestoringWhatWasRead:
    """The archive is the existing restore path's input, and nothing else."""

    async def test_the_library_arrives_whole(
        self,
        remote: httpx.AsyncClient,
        zotero: httpx.AsyncClient,
        session: AsyncSession,
        settings: Settings,
        tmp_path: Path,
    ) -> None:
        await zotero.post(
            "/users/4711/collections", headers=JSON, json=[{"name": "Whales", "key": "CCCC2345"}]
        )
        await seed(
            zotero,
            [
                {
                    "itemType": "book",
                    "title": "Moby-Dick",
                    "key": "AAAA2345",
                    "collections": ["CCCC2345"],
                    "tags": [{"tag": "fiction"}],
                }
            ],
        )
        user = await admin.create_user(session, username="ada")
        await session.commit()
        target = await get_library(session, LibraryType.USER, user.id)

        summary = await fetch_archive(
            api(remote), destination=tmp_path / "out.zip", target_user_id=user.id
        )
        restored = await transfer.import_library(
            session,
            archive=tmp_path / "out.zip",
            storage_root=settings.storage_path,
            into=target,
        )
        await session.commit()

        assert restored.version == summary.library_version
        assert restored.id == target.id

    async def test_it_refuses_to_merge_into_a_library_that_holds_something(
        self,
        remote: httpx.AsyncClient,
        zotero: httpx.AsyncClient,
        session: AsyncSession,
        settings: Settings,
        tmp_path: Path,
        client: httpx.AsyncClient,
    ) -> None:
        """`replace` is the difference between a copy and two libraries mixed."""
        await seed(zotero, [{"itemType": "book", "title": "Moby-Dick", "key": "AAAA2345"}])
        user = await admin.create_user(session, username="ada")
        local_key = await admin.create_api_key(session, username="ada", name="laptop")
        await session.commit()
        await client.post(
            f"/users/{user.id}/items",
            headers={"Zotero-API-Key": local_key.key, "Content-Type": "application/json"},
            json=[{"itemType": "book", "title": "Already here"}],
        )
        target = await get_library(session, LibraryType.USER, user.id)

        await fetch_archive(api(remote), destination=tmp_path / "out.zip", target_user_id=user.id)

        with pytest.raises(InvalidInputError):
            await transfer.import_library(
                session,
                archive=tmp_path / "out.zip",
                storage_root=settings.storage_path,
                into=target,
            )


class TestBeingAGoodGuest:
    """What zotero.org does and the fixture above does not."""

    def _throttling(self, answers: list[httpx.Response]) -> httpx.MockTransport:
        remaining = list(answers)

        def handle(request: httpx.Request) -> httpx.Response:
            return remaining.pop(0) if remaining else httpx.Response(200, json=[])

        return httpx.MockTransport(handle)

    async def test_a_429_is_waited_out_and_the_request_repeated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slept: list[float] = []

        async def record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("altero.services.zoteroapi.asyncio.sleep", record)
        transport = self._throttling(
            [
                httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, json={"ok": True}),
            ]
        )

        async with httpx.AsyncClient(transport=transport) as client:
            body = await ZoteroApi(key="k", client=client).json("/keys/current")

        assert body == {"ok": True}
        assert slept == [7.0]

    async def test_a_backoff_header_delays_the_next_request_not_this_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slept: list[float] = []

        async def record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("altero.services.zoteroapi.asyncio.sleep", record)
        transport = self._throttling(
            [
                httpx.Response(200, json={"first": True}, headers={"Backoff": "3"}),
                httpx.Response(200, json={"second": True}),
            ]
        )

        async with httpx.AsyncClient(transport=transport) as client:
            api = ZoteroApi(key="k", client=client)
            assert await api.json("/one") == {"first": True}
            assert slept == []
            assert await api.json("/two") == {"second": True}

        assert slept == [3.0]

    async def test_a_delay_that_is_not_whole_seconds_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The strictness the desktop client applies to the same headers."""
        slept: list[float] = []

        async def record(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr("altero.services.zoteroapi.asyncio.sleep", record)
        transport = self._throttling(
            [httpx.Response(200, json={"ok": True}, headers={"Backoff": "1.5"})]
        )

        async with httpx.AsyncClient(transport=transport) as client:
            api = ZoteroApi(key="k", client=client)
            await api.json("/one")
            await api.json("/two")

        assert slept == []

    async def test_it_gives_up_rather_than_hammering_forever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def record(seconds: float) -> None:
            return None

        monkeypatch.setattr("altero.services.zoteroapi.asyncio.sleep", record)
        transport = httpx.MockTransport(lambda request: httpx.Response(429))

        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ZoteroApiError):
                await ZoteroApi(key="k", client=client).json("/keys/current")

    async def test_pages_are_walked_by_start_rather_than_by_the_link_header(self) -> None:
        """A `Link` naming api.zotero.org would send a redirected fetch home."""
        seen: list[str] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            start = int(request.url.params.get("start", 0))
            page = [{"key": f"K{index}"} for index in range(start, min(start + 100, 150))]
            return httpx.Response(
                200,
                json=page,
                headers={
                    "Total-Results": "150",
                    "Link": '<https://api.zotero.org/somewhere/else>; rel="next"',
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            api = ZoteroApi(key="k", client=client, base_url="http://elsewhere.test")
            pages = [page async for page in api.paged("/users/1/items")]

        assert [len(page) for page in pages] == [100, 50]
        assert all(url.startswith("http://elsewhere.test/") for url in seen)


class TestALibraryThisServerCannotFullyStore:
    async def test_an_item_it_cannot_store_is_reported_rather_than_fatal(
        self, remote: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        """A schema newer than the vendored one must not lose the other items."""

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/keys/current":
                return httpx.Response(
                    200,
                    json={"userID": 4711, "username": "ada", "access": {"user": {"library": True}}},
                )
            if path == "/users/4711/items":
                if request.url.params.get("start", "0") != "0":
                    return httpx.Response(200, json=[], headers={"Total-Results": "2"})
                return httpx.Response(
                    200,
                    headers={"Total-Results": "2", "Last-Modified-Version": "12"},
                    json=[
                        {
                            "key": "AAAA2345",
                            "version": 12,
                            "data": {
                                "key": "AAAA2345",
                                "version": 12,
                                "itemType": "hologram",
                                "title": "From the future",
                            },
                        },
                        {
                            "key": "BBBB2345",
                            "version": 12,
                            "data": {
                                "key": "BBBB2345",
                                "version": 12,
                                "itemType": "book",
                                "title": "Ordinary",
                            },
                        },
                    ],
                )
            if path == "/users/4711/settings":
                return httpx.Response(200, json={})
            if path == "/users/4711/fulltext":
                return httpx.Response(200, json={})
            if path == "/users/4711/deleted":
                return httpx.Response(200, json={})
            if path == "/users/4711/tags":
                return httpx.Response(200, json={})
            return httpx.Response(200, json=[], headers={"Total-Results": "0"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            summary = await fetch_archive(
                ZoteroApi(key="k", client=client, base_url="http://zotero.test"),
                destination=tmp_path / "out.zip",
                target_user_id=4711,
            )

        assert summary.items == 1
        assert [key for key, _ in summary.skipped] == ["AAAA2345"]
        assert not summary.complete
