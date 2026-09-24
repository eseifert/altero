"""The attachment file protocol."""

import asyncio
import errno
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import IO

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType, StorageDownload
from altero.services import storage
from altero.services.auth import get_library
from altero.services.storage import file_path
from altero.settings import Settings
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

CONTENT = b"Call me Ishmael. Some years ago, never mind how long precisely..."
MD5 = hashlib.md5(CONTENT, usedforsecurity=False).hexdigest()


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


@pytest.fixture
async def attachment(session: AsyncSession, library: Library) -> str:
    await make_item(session, library, key="AAAA2345", item_type="attachment")
    return "AAAA2345"


def authorization(**overrides: object) -> dict[str, str]:
    form = {
        "md5": MD5,
        "filename": "moby.txt",
        "filesize": str(len(CONTENT)),
        "mtime": "1700000000000",
        "contentType": "text/plain",
        "charset": "utf-8",
    }
    form.update({k: str(v) for k, v in overrides.items()})
    return form


async def upload(client: httpx.AsyncClient, key: str, content: bytes = CONTENT) -> None:
    """Run the whole three-step upload for a file."""
    authorized = await client.post(
        f"/users/1/items/{key}/file",
        headers=AUTH | {"If-None-Match": "*"},
        data=authorization(),
    )
    body = authorized.json()
    await client.post(body["url"], content=content)
    await client.post(
        f"/users/1/items/{key}/file",
        headers=AUTH | {"If-None-Match": "*"},
        data={"upload": body["uploadKey"]},
    )


class TestAuthorization:
    async def test_authorization_returns_upload_instructions(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"url", "contentType", "prefix", "suffix", "uploadKey"}
        # There is no storage service to wrap the file for, so it is sent bare.
        assert body["prefix"] == ""
        assert body["suffix"] == ""

    async def test_a_precondition_is_required(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        response = await client.post(
            f"/users/1/items/{attachment}/file", headers=AUTH, data=authorization()
        )

        assert response.status_code == 428

    async def test_if_none_match_fails_when_a_file_is_present(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(md5="0" * 32),
        )

        assert response.status_code == 412

    async def test_if_match_must_name_the_current_file(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        stale = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-Match": "0" * 32},
            data=authorization(md5="1" * 32),
        )
        current = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-Match": MD5},
            data=authorization(md5="1" * 32, filesize=5),
        )

        assert stale.status_code == 412
        assert current.status_code == 200

    async def test_a_digest_with_no_bytes_is_not_a_file(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """An attachment can name a file this server has never held.

        A library migrated out of zotero.org whose files were kept on WebDAV is
        the ordinary way in: every attachment carries the digest and mtime the
        WebDAV server recorded, and none of the bytes. The client that still
        has them has to be able to send them, so the precondition has to read
        the store rather than the claim.
        """
        await make_item(
            session,
            library,
            key="WDAV2345",
            item_type="attachment",
            fields={"linkMode": "imported_file", "filename": "moby.txt", "md5": MD5},
        )
        await session.commit()

        authorized = await client.post(
            "/users/1/items/WDAV2345/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )

        assert authorized.status_code == 200
        assert "uploadKey" in authorized.json()

    async def test_the_file_a_claim_outlived_can_still_be_sent(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """And the whole upload goes through, whichever precondition is used.

        `If-Match` is what a client with a stored hash sends -- it took that
        hash from the item, which is why it matches -- and `If-None-Match` what
        one without sends. Both have to end with the bytes here, or the
        attachment is one that can neither be downloaded nor repaired.
        """
        await make_item(
            session,
            library,
            key="WDAV2345",
            item_type="attachment",
            fields={"linkMode": "imported_file", "filename": "moby.txt", "md5": MD5},
        )
        await session.commit()

        matched = await client.post(
            "/users/1/items/WDAV2345/file",
            headers=AUTH | {"If-Match": MD5},
            data=authorization(),
        )
        await upload(client, "WDAV2345")

        assert matched.status_code == 200
        assert (
            await client.get("/users/1/items/WDAV2345/file", headers=AUTH, follow_redirects=True)
        ).content == CONTENT

    async def test_a_swept_file_can_be_uploaded_again(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        """The same state reached from the other end: the bytes went away.

        An administrator sweeping unreferenced files, a restore without them,
        a disk replaced from an old backup. `stored_file` answers 404 for these
        already; the precondition agrees rather than insisting the file is
        there.
        """
        await upload(client, attachment)
        file_path(Path(settings.storage_path), MD5).unlink()

        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )

        assert response.status_code == 200
        assert "uploadKey" in response.json()

    async def test_a_known_file_needs_no_upload(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The same bytes attached twice are stored once.
        await make_item(session, library, key="AAAA2345", item_type="attachment")
        await make_item(session, library, key="BBBB2345", item_type="attachment")
        await upload(client, "AAAA2345")

        response = await client.post(
            "/users/1/items/BBBB2345/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )

        assert response.json() == {"exists": 1}
        assert (
            await client.get("/users/1/items/BBBB2345/file", headers=AUTH, follow_redirects=True)
        ).content == CONTENT

    async def test_a_malformed_digest_is_rejected(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(md5="nope"),
        )

        assert response.status_code == 400

    async def test_a_missing_field_is_rejected(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        form = authorization()
        del form["filename"]

        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=form,
        )

        assert response.status_code == 400

    async def test_only_attachments_take_files(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="BOOK2345", item_type="book")

        response = await client.post(
            "/users/1/items/BOOK2345/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )

        assert response.status_code == 400

    async def test_uploading_requires_write_permission(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=2, username="reader")
        await make_api_key(session, key="READONLY", user_id=2, library_write=False)
        library = await get_library(session, LibraryType.USER, 2)
        await make_item(session, library, key="AAAA2345", item_type="attachment")

        response = await client.post(
            "/users/2/items/AAAA2345/file",
            headers={"Zotero-API-Key": "READONLY", "If-None-Match": "*"},
            data=authorization(),
        )

        assert response.status_code == 403


class TestFormUpload:
    """The upload the mobile clients make, asking for a form with ``params=1``.

    Upstream answers that request with an S3 form, ``{url, params, uploadKey}``,
    and the Zotero iOS and Android applications send it as ``multipart/form-data``
    with the file in a part named ``file``. Neither reads ``prefix`` or ``suffix``.
    """

    async def authorize(self, client: httpx.AsyncClient, key: str) -> dict:
        response = await client.post(
            f"/users/1/items/{key}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(params=1),
        )
        assert response.status_code == 200
        return response.json()

    async def test_asking_for_params_answers_with_a_form(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        body = await self.authorize(client, attachment)

        # Upstream's keys, in upstream's order. The form is empty because
        # there is no storage service here asking for fields of its own.
        assert list(body) == ["url", "params", "uploadKey"]
        assert body["params"] == {}

    async def test_a_known_file_still_needs_no_upload(
        self, client: httpx.AsyncClient, attachment: str, session: AsyncSession, library: Library
    ) -> None:
        await upload(client, attachment)
        await make_item(session, library, key="BBBB2345", item_type="attachment")

        body = await self.authorize(client, "BBBB2345")

        assert body == {"exists": 1}

    async def test_a_multipart_upload_round_trips(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        body = await self.authorize(client, attachment)

        sent = await client.post(body["url"], files={"file": ("moby.txt", CONTENT, "text/plain")})
        assert sent.status_code == 201
        registered = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={"upload": body["uploadKey"]},
        )
        assert registered.status_code == 204

        response = await client.get(
            f"/users/1/items/{attachment}/file", headers=AUTH, follow_redirects=True
        )
        assert response.content == CONTENT

    async def test_the_form_fields_are_sent_back_beside_the_file(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        body = await self.authorize(client, attachment)

        # The clients post every field of `params` before the file, as S3
        # requires. There are none today, but a field is not the file.
        sent = await client.post(
            body["url"],
            data={"key": "ignored"},
            files={"file": ("moby.txt", CONTENT, "text/plain")},
        )

        assert sent.status_code == 201

    async def test_a_multipart_upload_is_checked_like_any_other(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        body = await self.authorize(client, attachment)

        sent = await client.post(
            body["url"], files={"file": ("moby.txt", b"x" * len(CONTENT), "text/plain")}
        )

        assert sent.status_code == 400

    async def test_a_multipart_upload_without_a_file_is_refused(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        body = await self.authorize(client, attachment)

        sent = await client.post(
            body["url"], data={"file": CONTENT.decode()}, files={"other": ("x", b"", "text/plain")}
        )

        assert sent.status_code == 400


class TestUploadAndRegistration:
    async def test_a_file_round_trips(self, client: httpx.AsyncClient, attachment: str) -> None:
        await upload(client, attachment)

        # A download is a redirect to the bytes, as it is upstream: see
        # `TestFileDownloads` in tests/test_client_quirks.py.
        response = await client.get(
            f"/users/1/items/{attachment}/file", headers=AUTH, follow_redirects=True
        )

        assert response.status_code == 200
        assert response.content == CONTENT

    async def test_registration_records_the_file_on_the_item(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        data = (await client.get(f"/users/1/items/{attachment}", headers=AUTH)).json()["data"]

        assert data["md5"] == MD5
        assert data["filename"] == "moby.txt"
        assert data["contentType"] == "text/plain"
        # A number, as upstream serves it, though it is stored as text like
        # every other field value. See `TestAttachmentModificationTime` in
        # `test_client_quirks.py` for what reads it and why the type matters.
        assert data["mtime"] == 1700000000000

    async def test_bytes_that_do_not_match_the_digest_are_refused(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        authorized = (
            await client.post(
                f"/users/1/items/{attachment}/file",
                headers=AUTH | {"If-None-Match": "*"},
                data=authorization(),
            )
        ).json()

        response = await client.post(authorized["url"], content=b"x" * len(CONTENT))

        assert response.status_code == 400

    async def test_bytes_of_the_wrong_length_are_refused(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        authorized = (
            await client.post(
                f"/users/1/items/{attachment}/file",
                headers=AUTH | {"If-None-Match": "*"},
                data=authorization(),
            )
        ).json()

        response = await client.post(authorized["url"], content=b"short")

        assert response.status_code == 400

    async def test_registering_before_the_bytes_arrive_is_refused(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        authorized = (
            await client.post(
                f"/users/1/items/{attachment}/file",
                headers=AUTH | {"If-None-Match": "*"},
                data=authorization(),
            )
        ).json()

        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={"upload": authorized["uploadKey"]},
        )

        assert response.status_code == 400

    async def test_an_unknown_upload_key_is_a_404(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        response = await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data={"upload": "nosuchkey"},
        )

        assert response.status_code == 404

    async def test_an_item_can_be_deleted_while_an_upload_is_authorized(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        # The authorization outlives the request that granted it and names the
        # item, so an item deleted between the first step and the third has to
        # take it along.
        await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )

        response = await client.delete(
            f"/users/1/items/{attachment}",
            headers=AUTH | {"If-Unmodified-Since-Version": "10"},
        )

        assert response.status_code == 204

    async def test_registration_advances_the_version(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        before = (await client.get(f"/users/1/items/{attachment}", headers=AUTH)).json()
        await upload(client, attachment)
        after = (await client.get(f"/users/1/items/{attachment}", headers=AUTH)).json()

        assert after["version"] > before["version"]


class TestDownload:
    async def test_an_item_without_a_file_is_a_404(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        assert (
            await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)
        ).status_code == 404

    async def test_the_view_route_serves_the_same_bytes(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        response = await client.get(f"/users/1/items/{attachment}/file/view", headers=AUTH)

        assert response.status_code == 200
        assert response.content == CONTENT
        assert "text/plain" in response.headers["content-type"]

    async def test_downloading_requires_authorisation(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        assert (await client.get(f"/users/1/items/{attachment}/file")).status_code == 403

    async def test_a_file_missing_from_disk_is_a_404(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        await upload(client, attachment)
        (settings.storage_path / MD5[:2] / MD5).unlink()

        response = await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)

        assert response.status_code == 404


class TestDownloadPermission:
    """Where the redirect leads, and what reaching it takes.

    The client does not follow this redirect. It reads the three `Zotero-File-*`
    headers off the 302 and then makes a second, *fresh* request for the
    location, carrying none of the first request's headers -- see
    `Zotero.HTTP.download` in `zfs.js`, which is passed no `headers` at all.
    So the location has to authorize itself, and it does it the way
    `/storage/upload/<key>` does in the other direction: the key in the path is
    the credential, it names one file, and it expires.
    """

    async def test_the_location_is_reachable_with_no_headers_at_all(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        redirect = await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)
        assert redirect.status_code == 302

        # No AUTH: this is the request the client actually makes.
        bytes_response = await client.get(redirect.headers["location"])

        assert bytes_response.status_code == 200
        assert bytes_response.content == CONTENT

    async def test_the_location_carries_no_api_key(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        # A key grants the whole account and never expires; every reverse proxy
        # writes the request line to its access log.
        await upload(client, attachment)

        redirect = await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)

        assert KEY not in redirect.headers["location"]
        assert redirect.headers["cache-control"] == "no-store"

    async def test_the_permission_is_not_an_api_key(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        # It opens one file and nothing else, which is the whole point of it
        # being something other than the key.
        await upload(client, attachment)
        redirect = await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)
        permission = redirect.headers["location"].rsplit("/", 1)[-1]

        assert (await client.get("/users/1/items", params={"key": permission})).status_code == 403
        assert (
            await client.get(f"/users/1/items/{attachment}/file", params={"key": permission})
        ).status_code == 403

    async def test_it_can_be_spent_more_than_once(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        # `Zotero.HTTP.download` retries the same URL after a 5xx or a dropped
        # connection. One-shot would turn every such retry into a failed sync.
        await upload(client, attachment)
        location = (await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)).headers[
            "location"
        ]

        assert (await client.get(location)).status_code == 200
        assert (await client.get(location)).status_code == 200

    async def test_an_expired_permission_opens_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, attachment: str
    ) -> None:
        await upload(client, attachment)
        location = (await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)).headers[
            "location"
        ]

        await session.execute(
            update(StorageDownload).values(expires=datetime(2020, 1, 1, tzinfo=None))
        )
        await session.commit()

        assert (await client.get(location)).status_code == 404

    async def test_a_permission_nobody_issued_opens_nothing(
        self, client: httpx.AsyncClient, attachment: str
    ) -> None:
        await upload(client, attachment)

        assert (await client.get("/storage/download/" + "X" * 24)).status_code == 404

    async def test_it_does_not_follow_the_item_to_another_file(
        self, client: httpx.AsyncClient, session: AsyncSession, attachment: str
    ) -> None:
        # The 302 promised a digest in `Zotero-File-MD5`. Serving whatever the
        # attachment holds later would break that promise silently.
        await upload(client, attachment)
        location = (await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)).headers[
            "location"
        ]

        replacement = b"Call me something else entirely."
        authorized = (
            await client.post(
                f"/users/1/items/{attachment}/file",
                headers=AUTH | {"If-Match": MD5},
                data=authorization(
                    md5=hashlib.md5(replacement, usedforsecurity=False).hexdigest(),
                    filesize=len(replacement),
                ),
            )
        ).json()
        await client.post(authorized["url"], content=replacement)
        await client.post(
            f"/users/1/items/{attachment}/file",
            headers=AUTH | {"If-Match": MD5},
            data={"upload": authorized["uploadKey"]},
        )

        assert (await client.get(location)).status_code == 404

    async def test_deleting_the_item_takes_its_permissions(
        self, client: httpx.AsyncClient, session: AsyncSession, attachment: str
    ) -> None:
        # The row names the item by id, so leaving one behind fails the foreign
        # key on the way out.
        await upload(client, attachment)
        location = (await client.get(f"/users/1/items/{attachment}/file", headers=AUTH)).headers[
            "location"
        ]

        version = (await client.get(f"/users/1/items/{attachment}", headers=AUTH)).headers[
            "Last-Modified-Version"
        ]
        deleted = await client.delete(
            f"/users/1/items/{attachment}",
            headers=AUTH | {"If-Unmodified-Since-Version": version},
        )
        assert deleted.status_code == 204

        assert await session.scalar(select(func.count()).select_from(StorageDownload)) == 0
        assert (await client.get(location)).status_code == 404


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A file store of this test's own, where the settings fixture puts one."""
    return tmp_path / "storage"


class _HalfWritten:
    """A file that takes half of what it is given and then gives up.

    What a full disk looks like from inside `store_file`: what was written
    stays written, and the failure arrives before anything is moved.
    """

    def __init__(self, handle: IO[bytes]) -> None:
        self._handle = handle

    def __enter__(self) -> _HalfWritten:
        return self

    def __exit__(self, *exception: object) -> None:
        self._handle.close()

    def fileno(self) -> int:
        return self._handle.fileno()

    def flush(self) -> None:
        self._handle.flush()

    def write(self, body: bytes) -> int:
        self._handle.write(body[: len(body) // 2])
        self._handle.flush()
        raise OSError(errno.ENOSPC, "No space left on device")


def half_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every write into the store stop half way through."""
    opened = os.fdopen

    def fdopen(descriptor: int, mode: str) -> _HalfWritten:
        return _HalfWritten(opened(descriptor, mode))

    monkeypatch.setattr(storage.os, "fdopen", fdopen)


def refuse(*arguments: object, **named: object) -> None:
    """Fail the way a remote mount does: at the last step, having said nothing."""
    raise OSError(errno.EIO, "Input/output error")


class TestAtomicWrites:
    """A file is in the store whole or not at all.

    Everything downstream asks `Path.is_file` and believes the answer, so a
    file that was never finished is worse than no file: `authorize` hands it
    to every later upload of that digest as ``{"exists": 1}``, and the client
    records the attachment as synced for good. Reported as issue #11.
    """

    def test_a_write_that_fails_part_way_leaves_nothing_behind(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        half_writes(monkeypatch)

        with pytest.raises(OSError, match="No space left"):
            storage.store_file(store, MD5, CONTENT)

        assert not file_path(store, MD5).exists()
        # Including the half that was written: a name nothing sweeps would
        # trade a torn file for a leak.
        assert list(file_path(store, MD5).parent.iterdir()) == []

    def test_a_write_that_cannot_be_synced_leaves_nothing_behind(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A network or FUSE mount reports a lost write at sync rather than at
        # write, which is the deployment the report came from.
        monkeypatch.setattr(storage.os, "fsync", refuse)

        with pytest.raises(OSError, match="Input/output error"):
            storage.store_file(store, MD5, CONTENT)

        assert list(file_path(store, MD5).parent.iterdir()) == []

    def test_a_move_that_is_refused_leaves_the_file_that_was_there(
        self, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Several object-store mounts refuse to rename over an existing file.
        # Copying instead would be the torn write this is here to prevent.
        storage.store_file(store, MD5, CONTENT)
        monkeypatch.setattr(storage.os, "replace", refuse)

        with pytest.raises(OSError, match="Input/output error"):
            storage.store_file(store, MD5, b"other bytes")

        assert file_path(store, MD5).read_bytes() == CONTENT
        assert len(list(file_path(store, MD5).parent.iterdir())) == 1

    def test_a_stored_file_can_be_read_from_outside_the_server(self, store: Path) -> None:
        # `mkstemp` creates 0600 and the store has always held 0644, which a
        # backup running as somebody else depends on.
        storage.store_file(store, MD5, CONTENT)

        assert file_path(store, MD5).stat().st_mode & 0o777 == 0o644

    async def test_two_writers_of_one_digest_leave_one_whole_file(self, store: Path) -> None:
        """Each writes under a name of its own, so neither can see the other's.

        Two clients zipping one snapshot send different archives under the
        same digest, so this is not hypothetical: a shared staging name would
        let one of them move a file the other was still writing.
        """
        first = b"a" * (1024 * 1024)
        second = b"b" * len(first)

        await asyncio.gather(
            *(
                asyncio.to_thread(storage.store_file, store, MD5, body)
                for body in (first, second) * 4
            )
        )

        assert file_path(store, MD5).read_bytes() in (first, second)
        assert len(list(file_path(store, MD5).parent.iterdir())) == 1

    def test_a_read_in_flight_survives_the_file_being_replaced(self, store: Path) -> None:
        # `os.replace` unlinks the name, not the bytes: a download already
        # under way reads the file it opened to the end.
        storage.store_file(store, MD5, CONTENT)

        with file_path(store, MD5).open("rb") as reading:
            storage.store_file(store, MD5, b"other bytes")

            assert reading.read() == CONTENT


async def send(client: httpx.AsyncClient, key: str, content: bytes = CONTENT) -> str:
    """Authorize an upload and send the bytes. Returns the key to register with."""
    authorized = (
        await client.post(
            f"/users/1/items/{key}/file",
            headers=AUTH | {"If-None-Match": "*"},
            data=authorization(),
        )
    ).json()
    await client.post(authorized["url"], content=content)
    return str(authorized["uploadKey"])


async def finish(client: httpx.AsyncClient, key: str, upload_key: str) -> httpx.Response:
    """Take the third step of an upload."""
    return await client.post(
        f"/users/1/items/{key}/file",
        headers=AUTH | {"If-None-Match": "*"},
        data={"upload": upload_key},
    )


class TestRegistrationChecksTheStoredFile:
    """The bytes are read back before the attachment is said to have them.

    The upload arrives whole or not at all, but a store can still take a write
    and lose it -- which is what a network or FUSE mount does -- and this is
    the last moment anything can be checked: a snapshot is stored under the
    digest of the file inside its archive, and the archive's own digest goes
    when the upload row does.
    """

    async def test_a_truncated_stored_file_is_refused(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        upload_key = await send(client, attachment)
        file_path(Path(settings.storage_path), MD5).write_bytes(CONTENT[:10])

        assert (await finish(client, attachment, upload_key)).status_code == 400

    async def test_bytes_that_changed_under_the_store_are_refused(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        # Same length, so only reading them back catches it.
        upload_key = await send(client, attachment)
        file_path(Path(settings.storage_path), MD5).write_bytes(b"?" * len(CONTENT))

        assert (await finish(client, attachment, upload_key)).status_code == 400

    async def test_a_file_that_went_away_is_refused(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        upload_key = await send(client, attachment)
        file_path(Path(settings.storage_path), MD5).unlink()

        assert (await finish(client, attachment, upload_key)).status_code == 400

    async def test_a_refused_file_is_removed_so_it_can_be_sent_again(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        """Which is the whole point of refusing.

        Left where it is, the next upload of those bytes is answered
        ``{"exists": 1}`` and the damage spreads to another attachment.
        Removed, the item claims a digest nothing backs -- a state the client
        can mend by sending the file again.
        """
        upload_key = await send(client, attachment)
        path = file_path(Path(settings.storage_path), MD5)
        path.write_bytes(CONTENT[:10])
        await finish(client, attachment, upload_key)

        assert not path.exists()

        await upload(client, attachment)
        assert (
            await client.get(
                f"/users/1/items/{attachment}/file", headers=AUTH, follow_redirects=True
            )
        ).content == CONTENT

    async def test_a_refused_registration_attaches_nothing(
        self, client: httpx.AsyncClient, attachment: str, settings: Settings
    ) -> None:
        upload_key = await send(client, attachment)
        file_path(Path(settings.storage_path), MD5).write_bytes(CONTENT[:10])
        await finish(client, attachment, upload_key)

        item = await client.get(f"/users/1/items/{attachment}", headers=AUTH)
        assert "md5" not in item.json()["data"]
        # And the library version the failed write took is given back.
        assert item.headers["Last-Modified-Version"] == "10"
