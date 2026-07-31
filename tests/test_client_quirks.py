"""Behaviours the real Zotero client needs, found by running it.

Each of these was a live failure: a 500 or a stalled upload with a green test
suite. They are collected here because they share a cause — the client does
things the published documentation does not mention.
"""

import gzip
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestGzippedRequests:
    """The client compresses full-text uploads.

    It sends `Content-Encoding: gzip` with a gzipped body. Reading that as UTF-8
    fails on the second byte of the gzip magic number, so every upload answered
    500 and the client retried forever with a growing backoff.
    """

    async def test_a_gzipped_body_is_accepted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        body = json.dumps([{"key": "AAAA2345", "content": "Some text"}]).encode()

        response = await client.post(
            "/users/1/fulltext",
            headers=AUTH
            | {
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
                "If-Unmodified-Since-Version": "10",
            },
            content=gzip.compress(body),
        )

        assert response.status_code == 200
        assert response.json()["failed"] == {}

    async def test_the_content_survives_compression(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Non-ASCII is where a mishandled encoding shows up first.
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        text = "Sicherheitslücken: zügiges Update — größer"
        body = json.dumps([{"key": "AAAA2345", "content": text}]).encode()

        await client.post(
            "/users/1/fulltext",
            headers=AUTH
            | {
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
                "If-Unmodified-Since-Version": "10",
            },
            content=gzip.compress(body),
        )

        stored = (await client.get("/users/1/items/AAAA2345/fulltext", headers=AUTH)).json()
        assert stored["content"] == text

    async def test_an_uncompressed_body_still_works(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.post(
            "/users/1/fulltext",
            headers=AUTH | {"If-Unmodified-Since-Version": "10"},
            json=[{"key": "AAAA2345", "content": "plain"}],
        )

        assert response.status_code == 200

    async def test_a_corrupt_gzip_body_is_a_400(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Better than a 500 with a traceback in it.
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.post(
            "/users/1/fulltext",
            headers=AUTH | {"Content-Encoding": "gzip", "If-Unmodified-Since-Version": "10"},
            content=b"not actually gzipped",
        )

        assert response.status_code == 400


class TestUploadUrl:
    async def test_the_upload_url_is_absolute(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The client passes this straight to XMLHttpRequest.open(), which
        # rejects a bare path with "is not a valid URL".
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        body = (
            await client.post(
                "/users/1/items/AAAA2345/file",
                headers=AUTH | {"If-None-Match": "*"},
                data={
                    "md5": "0" * 32,
                    "filename": "f.txt",
                    "filesize": "5",
                    "mtime": "1700000000000",
                },
            )
        ).json()

        assert body["url"].startswith("http://")
        assert body["url"].endswith(f"/storage/upload/{body['uploadKey']}")


class TestZippedUploads:
    """A snapshot is uploaded as a ZIP.

    `md5` is then the digest of the *original* file, while the bytes on the wire
    are the ZIP and `filesize` is the ZIP's size. Checking the transfer against
    `md5` therefore rejects every snapshot the connector saves.
    """

    CONTENT = b"<html>a snapshot</html>"
    ZIPPED = b"PK\x03\x04 pretend this is a zip"

    async def test_a_zipped_upload_is_validated_against_the_zip_digest(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        original_md5 = hashlib.md5(self.CONTENT, usedforsecurity=False).hexdigest()
        zip_md5 = hashlib.md5(self.ZIPPED, usedforsecurity=False).hexdigest()

        authorized = (
            await client.post(
                "/users/1/items/AAAA2345/file",
                headers=AUTH | {"If-None-Match": "*"},
                data={
                    "md5": original_md5,
                    "filename": "page.html",
                    "filesize": str(len(self.ZIPPED)),
                    "mtime": "1700000000000",
                    "zipMD5": zip_md5,
                    "zipFilename": "AAAA2345.zip",
                },
            )
        ).json()

        upload = await client.post(authorized["url"], content=self.ZIPPED)
        assert upload.status_code == 201

        registered = await client.post(
            "/users/1/items/AAAA2345/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={"upload": authorized["uploadKey"]},
        )
        assert registered.status_code == 204

    async def test_the_item_records_the_original_digest(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The client sends this back as If-Match next time, so recording the
        # zip's digest instead would make every later upload fail with 412.
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        original_md5 = hashlib.md5(self.CONTENT, usedforsecurity=False).hexdigest()
        zip_md5 = hashlib.md5(self.ZIPPED, usedforsecurity=False).hexdigest()

        authorized = (
            await client.post(
                "/users/1/items/AAAA2345/file",
                headers=AUTH | {"If-None-Match": "*"},
                data={
                    "md5": original_md5,
                    "filename": "page.html",
                    "filesize": str(len(self.ZIPPED)),
                    "mtime": "1700000000000",
                    "zipMD5": zip_md5,
                    "zipFilename": "AAAA2345.zip",
                },
            )
        ).json()
        await client.post(authorized["url"], content=self.ZIPPED)
        await client.post(
            "/users/1/items/AAAA2345/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={"upload": authorized["uploadKey"]},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        assert data["md5"] == original_md5
        assert data["filename"] == "page.html"

    async def test_the_wrong_zip_digest_is_still_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        authorized = (
            await client.post(
                "/users/1/items/AAAA2345/file",
                headers=AUTH | {"If-None-Match": "*"},
                data={
                    "md5": "0" * 32,
                    "filename": "page.html",
                    "filesize": str(len(self.ZIPPED)),
                    "mtime": "1700000000000",
                    "zipMD5": "1" * 32,
                    "zipFilename": "AAAA2345.zip",
                },
            )
        ).json()

        response = await client.post(authorized["url"], content=self.ZIPPED)

        assert response.status_code == 400


class TestErrorBodies:
    async def test_an_unexpected_failure_does_not_leak_a_traceback(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # The client logs the whole response body, so a traceback ends up in the
        # user's debug output and in bug reports.
        response = await client.post(
            "/users/1/fulltext",
            headers=AUTH | {"Content-Encoding": "gzip", "If-Unmodified-Since-Version": "10"},
            content=b"\x1f\x8b broken",
        )

        assert response.status_code == 400
        assert "Traceback" not in response.text
        assert "altero/api" not in response.text
