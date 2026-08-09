"""The attachment file protocol."""

import hashlib
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
