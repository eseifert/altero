"""An attachment's digest names a file to serve, so it must stay a digest.

Reported as an authenticated path traversal (GitHub #62): ``md5`` is validated
on the upload path but was stored verbatim when set through the ordinary item
write, and every download route joined that stored string onto the file store's
root. An absolute or dotted value therefore resolved a file outside the store.

Two defences, tested here: the write path refuses a non-digest as upstream does,
and :func:`storage.file_path` refuses one too, so a row poisoned before the
first fix can still never name a path outside the store.
"""

from pathlib import Path

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import NotFoundError
from altero.models import Library, LibraryType
from altero.services import storage
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}

# Values that name something other than a stored file.
TRAVERSALS = ("/etc/os-release", "../../../../etc/passwd", "..", "deadbeef", "g" * 32)

# None of these is a digest `file_path` may build a path from. The two beyond
# the traversals are handled on the write path rather than refused: an empty
# md5 clears the field, and an uppercase digest is normalised to lowercase.
NON_DIGESTS = (*TRAVERSALS, "", "ABCDEF0123456789ABCDEF0123456789")


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


def attachment(md5: str) -> dict[str, object]:
    return {
        "itemType": "attachment",
        "linkMode": "imported_file",
        "filename": "x",
        "contentType": "text/plain",
        "md5": md5,
        "mtime": 1700000000000,
    }


class TestTheWritePathRefusesANonDigest:
    @pytest.mark.parametrize("md5", TRAVERSALS)
    async def test_a_traversal_md5_is_a_clean_failure(
        self, client: httpx2.AsyncClient, library: Library, md5: str
    ) -> None:
        response = await client.post("/users/1/items", headers=AUTH, json=[attachment(md5)])

        assert response.status_code == 200
        body = response.json()
        assert body["successful"] == {}
        assert body["failed"]["0"]["code"] == 400
        assert "valid MD5" in body["failed"]["0"]["message"]

    async def test_a_real_digest_is_stored_lowercased(
        self, client: httpx2.AsyncClient, library: Library
    ) -> None:
        digest = "ABCDEF0123456789abcdef0123456789"
        response = await client.post("/users/1/items", headers=AUTH, json=[attachment(digest)])

        assert response.status_code == 200
        key = response.json()["success"]["0"]
        item = (await client.get(f"/users/1/items/{key}", headers=AUTH)).json()["data"]
        assert item["md5"] == digest.lower()


class TestTheReadPathRefusesAPoisonedRow:
    """A row written before the first fix, or by some path that skips it."""

    async def test_download_of_a_traversal_md5_is_not_found(
        self, client: httpx2.AsyncClient, session: AsyncSession, library: Library, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret"
        secret.write_text("PRETTY_NAME=secret")
        await make_item(
            session,
            library,
            key="POISONED2",
            item_type="attachment",
            fields={"linkMode": "imported_file", "filename": "x", "md5": str(secret)},
        )
        await session.commit()

        for route in ("file", "file/content", "file/view"):
            response = await client.get(f"/users/1/items/POISONED2/{route}", headers=AUTH)
            assert response.status_code == 404, route
            assert "secret" not in response.text


class TestFilePath:
    def test_refuses_anything_that_is_not_a_digest(self, tmp_path: Path) -> None:
        for value in NON_DIGESTS:
            with pytest.raises(NotFoundError):
                storage.file_path(tmp_path, value)

    def test_builds_the_fanned_out_path_for_a_digest(self, tmp_path: Path) -> None:
        digest = "abcdef0123456789abcdef0123456789"
        assert storage.file_path(tmp_path, digest) == tmp_path / "ab" / digest

    def test_is_file_digest(self) -> None:
        assert storage.is_file_digest("abcdef0123456789abcdef0123456789")
        assert not storage.is_file_digest("ABCDEF0123456789abcdef0123456789")
        assert not storage.is_file_digest("/etc/passwd")
        assert not storage.is_file_digest("abcdef0123456789abcdef012345678")
