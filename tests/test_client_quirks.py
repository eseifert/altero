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
from tests.factories import make_api_key, make_group, make_item, make_user

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
    # The client's own key reaches groups, which is what makes the group sync
    # in `TestGroupVersions` the one the client actually performs.
    await make_api_key(session, key=KEY, user_id=1, all_groups_read=True, all_groups_write=True)
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


class TestGroupVersions:
    """The client asks for its groups by version, every sync.

    `GET /users/<id>/groups?format=versions` is the first thing
    `Sync.Runner.checkLibraries` does with groups, and it iterates the answer
    with `for (groupID in ...)`. Answering with the JSON array the default
    format returns hands it array indices instead of group ids: with one group
    it read `0`, called `getGroup(0)`, and the sync died on "Group ID not
    provided" before any library was synced. An empty library hid it -- an
    empty array iterates to nothing.
    """

    @pytest.fixture
    async def group(self, session: AsyncSession, library: Library) -> Library:
        group = await make_group(session, group_id=42, owner_id=1, name="Kollaps")
        group.version = 7
        await session.commit()
        return group

    async def test_the_versions_format_is_keyed_by_group_id(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        response = await client.get("/users/1/groups?format=versions", headers=AUTH)

        assert response.status_code == 200
        assert response.json() == {"42": 7}

    async def test_a_user_with_no_groups_answers_an_empty_object(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/groups?format=versions", headers=AUTH)

        assert response.json() == {}

    async def test_the_version_is_the_one_the_group_itself_reports(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        # The client compares the two to decide whether to re-download the
        # group, so a mismatch is either a download every sync or none ever.
        versions = (await client.get("/users/1/groups?format=versions", headers=AUTH)).json()
        rendered = (await client.get("/groups/42", headers=AUTH)).json()

        assert versions["42"] == rendered["version"]

    async def test_the_default_format_is_still_the_group_listing(
        self, client: httpx.AsyncClient, group: Library
    ) -> None:
        response = await client.get("/users/1/groups", headers=AUTH)

        assert [rendered["id"] for rendered in response.json()] == [42]


class TestFileDownloads:
    """The client reads a download's metadata off a redirect, and only there.

    `zfs.js` populates `requestData` inside `asyncOnChannelRedirect`, from
    `Zotero-File-Modification-Time`, `Zotero-File-MD5` and
    `Zotero-File-Compressed` on the 302. Answering the download with the bytes
    and a 200 means that handler never runs, so `processDownload` is reached
    with nothing set and throws "'data.mtime' not set" -- which is a file sync
    error for every attachment in the library, on every sync.
    """

    CONTENT = b"%PDF-1.4 a paper"
    ZIPPED = b"PK\x03\x04 pretend this is a zip"

    async def _upload(
        self,
        client: httpx.AsyncClient,
        key: str,
        body: bytes,
        *,
        filename: str = "paper.pdf",
        zipped: bool = False,
    ) -> str:
        """Upload ``body`` for item ``key``, returning the recorded digest."""
        digest = hashlib.md5(self.CONTENT if zipped else body, usedforsecurity=False).hexdigest()
        form = {
            "md5": digest,
            "filename": filename,
            "filesize": str(len(body)),
            "mtime": "1700000000000",
        }
        if zipped:
            form |= {
                "zipMD5": hashlib.md5(body, usedforsecurity=False).hexdigest(),
                "zipFilename": f"{key}.zip",
            }

        authorized = (
            await client.post(
                f"/users/1/items/{key}/file",
                headers=AUTH | {"If-None-Match": "*"},
                data=form,
            )
        ).json()
        await client.post(authorized["url"], content=body)
        await client.post(
            f"/users/1/items/{key}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={"upload": authorized["uploadKey"]},
        )
        return digest

    async def test_the_download_redirects_and_carries_the_file_headers(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        digest = await self._upload(client, "AAAA2345", self.CONTENT)

        response = await client.get("/users/1/items/AAAA2345/file", headers=AUTH)

        assert response.status_code == 302
        assert response.headers["Zotero-File-Modification-Time"] == "1700000000000"
        assert response.headers["Zotero-File-MD5"] == digest
        assert response.headers["Zotero-File-Compressed"] == "No"
        assert response.headers["Location"]

    async def test_the_redirect_leads_to_the_bytes(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await self._upload(client, "AAAA2345", self.CONTENT)

        response = await client.get(
            "/users/1/items/AAAA2345/file", headers=AUTH, follow_redirects=True
        )

        assert response.status_code == 200
        assert response.content == self.CONTENT

    async def test_a_zipped_upload_is_announced_as_compressed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The stored bytes are the archive; the item's `md5` describes the file
        # inside it. Saying `No` here would have the client write the ZIP itself
        # to disk under the attachment's name.
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await self._upload(client, "AAAA2345", self.ZIPPED, filename="page.html", zipped=True)

        response = await client.get("/users/1/items/AAAA2345/file", headers=AUTH)

        assert response.headers["Zotero-File-Compressed"] == "Yes"

    async def test_an_attachment_that_is_itself_a_zip_is_not_compressed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # A .docx or .epub is a ZIP too. What distinguishes the wrapper is that
        # its bytes hash to something other than the digest the item claims.
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await self._upload(client, "AAAA2345", self.ZIPPED, filename="thesis.docx")

        response = await client.get("/users/1/items/AAAA2345/file", headers=AUTH)

        assert response.headers["Zotero-File-Compressed"] == "No"

    async def test_a_missing_file_is_still_a_404(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The client treats 404 as "nothing to download" and marks the
        # attachment in sync, so it must not become a redirect to nowhere.
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.get("/users/1/items/AAAA2345/file", headers=AUTH)

        assert response.status_code == 404


#: An attachment's fields in an order no client would send them in, which is
#: what a field table with no order of its own can hand back.
SCRAMBLED = {
    "url": "https://example.invalid/paper.pdf",
    "contentType": "application/pdf",
    "filename": "paper.pdf",
    "linkMode": "imported_url",
    "title": "Volltext",
}


class TestAttachmentFieldOrder:
    """`linkMode` has to be emitted before `filename`.

    `Zotero.Item.fromJSON` walks the object with `for (let field in json)` and
    sets the attachment path when it reaches `filename`, which throws "Link mode
    must be set before setting attachment path" if `linkMode` has not been seen
    yet. The item is then queued in `syncQueue` and retried forever.

    Field rows carry no order of their own, so the order they were written in is
    whatever the database hands back -- insertion order under SQLite, nothing in
    particular under PostgreSQL.
    """

    async def test_link_mode_precedes_filename(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", item_type="attachment", fields=SCRAMBLED)

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        keys = list(data)

        assert keys.index("linkMode") < keys.index("filename")

    async def test_the_order_is_the_one_upstream_emits(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Read off an imported_url attachment as zotero.org serves it.
        await make_item(
            session,
            library,
            key="AAAA2345",
            item_type="attachment",
            fields=SCRAMBLED
            | {"charset": "utf-8", "md5": "0" * 32, "mtime": "1700000000000", "note": ""},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        emitted = [
            key for key in data if key in SCRAMBLED or key in {"charset", "md5", "mtime", "note"}
        ]

        assert emitted == [
            "linkMode",
            "title",
            "url",
            "contentType",
            "charset",
            "filename",
            "md5",
            "mtime",
            "note",
        ]

    async def test_a_normal_item_follows_the_schema(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="BBBB2345",
            item_type="journalArticle",
            fields={"date": "2020", "title": "A paper", "DOI": "10.0/x"},
        )

        data = (await client.get("/users/1/items/BBBB2345", headers=AUTH)).json()["data"]
        emitted = [key for key in data if key in {"title", "date", "DOI"}]

        assert emitted == ["title", "date", "DOI"]


class TestAttachmentModificationTime:
    """`mtime` is a number in the item JSON, where every field beside it is text.

    api.zotero.org serves `"mtime": 1299848186000` -- read off an attachment in
    public group 91 -- with `md5` next to it as a string. `Item.fromJSON`
    ignores both, so an ordinary sync never notices the difference, but
    `Zotero.Sync.Storage.Local.resolveConflicts` assigns `conflict.right.mtime`
    straight from the cached remote JSON when a file conflict is settled in
    favour of the local copy, and the `attachmentSyncedModificationTime` setter
    throws "must be a number" on anything else. A file conflict is exactly what
    two clients syncing one library produce.
    """

    async def test_it_is_served_as_a_number(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="AAAA2345",
            item_type="attachment",
            fields=SCRAMBLED | {"md5": "0" * 32, "mtime": "1785701798544"},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]

        assert data["mtime"] == 1785701798544
        assert not isinstance(data["mtime"], str)

    async def test_the_digest_beside_it_stays_text(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # `md5` is a hex digest, which happens to be all digits often enough
        # that coercing by shape rather than by name would eventually turn one
        # into a number.
        await make_item(
            session,
            library,
            key="AAAA2345",
            item_type="attachment",
            fields=SCRAMBLED | {"md5": "1" * 32, "mtime": "1785701798544"},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]

        assert data["md5"] == "1" * 32

    async def test_it_keeps_its_place_in_the_order(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Emitting it as a number must not move it, for the reason
        # `TestAttachmentFieldOrder` exists.
        await make_item(
            session,
            library,
            key="AAAA2345",
            item_type="attachment",
            fields=SCRAMBLED | {"md5": "0" * 32, "mtime": "1785701798544"},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        keys = list(data)

        assert keys.index("filename") < keys.index("md5") < keys.index("mtime")

    async def test_something_that_is_not_a_timestamp_is_left_alone(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Nothing stops a write storing text here, and serving it back as it
        # was stored is better than a 500 on reading the library.
        await make_item(
            session,
            library,
            key="AAAA2345",
            item_type="attachment",
            fields=SCRAMBLED | {"mtime": "whenever"},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]

        assert data["mtime"] == "whenever"


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
