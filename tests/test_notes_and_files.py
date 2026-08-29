"""What a credential that gave up notes or file access may read.

``notes_read`` and ``files_read`` have been on an API key since the first
migration, and an OAuth token says the same two things as ``notes.read`` and
``files.read``. They were stored, reported on ``/keys/current``, listed on the
consent screen -- and enforced nowhere, so a token asking only for
``library.read`` read every note in the library and downloaded every file in
it. These are the negative tests that were missing.

The shape is upstream's. A note is *hidden* rather than redacted: 404 by key,
absent from every listing, and uncounted in ``numChildren``
(``Zotero_Permissions::canAccessObject`` and the ``itemTypeID != 1`` clause in
``Zotero_Items::search``). Files answer 403
(``ItemsController::_handleFileRequest``).
"""

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from altero.settings import Settings
from tests.factories import make_api_key, make_item, make_user

#: A key that gave up both permissions, and one that kept them.
NARROW = "R3strict3dK3yNoNot3sNoFil"
FULL = "P9NiFoyLeZu2bZNvvuQPDWsd"

WITHOUT = {"Zotero-API-Key": NARROW}
WITH = {"Zotero-API-Key": FULL}

CONTENT = b"Call me Ishmael."
MD5 = hashlib.md5(CONTENT, usedforsecurity=False).hexdigest()

BOOK = "BOOK1234"
NOTE = "NOTE1234"
LOOSE = "LOOSE123"
ATTACHMENT = "ATTA1234"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
    )


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    """A library holding a book with a child note, a loose note and a file."""
    await make_user(session, user_id=1)
    await make_api_key(session, key=FULL, user_id=1, name="Everything")
    await make_api_key(
        session, key=NARROW, user_id=1, name="Narrow", notes_read=False, files_read=False
    )

    library = await get_library(session, LibraryType.USER, 1)
    book = await make_item(session, library, key=BOOK, item_type="book", fields={"title": "Moby"})
    await make_item(
        session,
        library,
        key=NOTE,
        item_type="note",
        parent=book,
        fields={"note": "<p>confidential</p>"},
    )
    await make_item(
        session, library, key=LOOSE, item_type="note", fields={"note": "<p>also secret</p>"}
    )
    await make_item(session, library, key=ATTACHMENT, item_type="attachment", parent=book)

    library.version = 10
    await session.commit()
    return library


async def upload(client: httpx.AsyncClient) -> None:
    """Put bytes on the attachment, with the key that may."""
    authorized = await client.post(
        f"/users/1/items/{ATTACHMENT}/file",
        headers=WITH | {"If-None-Match": "*"},
        data={
            "md5": MD5,
            "filename": "moby.txt",
            "filesize": str(len(CONTENT)),
            "mtime": "1700000000000",
            "contentType": "text/plain",
            "charset": "utf-8",
        },
    )
    body = authorized.json()
    await client.post(body["url"], content=CONTENT)
    await client.post(
        f"/users/1/items/{ATTACHMENT}/file",
        headers=WITH | {"If-None-Match": "*"},
        data={"upload": body["uploadKey"]},
    )


def keys_in(response: httpx.Response) -> set[str]:
    return {entry["key"] for entry in response.json()}


class TestANoteIsHiddenWithoutNotesAccess:
    """Hidden, not redacted: upstream never serves an emptied note."""

    async def test_a_note_by_key_is_not_found(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get(f"/users/1/items/{NOTE}", headers=WITHOUT)

        assert response.status_code == 404
        assert "confidential" not in response.text

    async def test_no_note_appears_in_the_item_listing(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items", headers=WITHOUT)

        assert keys_in(response) == {BOOK, ATTACHMENT}

    async def test_no_note_appears_among_top_level_items(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items/top", headers=WITHOUT)

        assert keys_in(response) == {BOOK}

    async def test_no_note_appears_among_a_parent_s_children(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get(f"/users/1/items/{BOOK}/children", headers=WITHOUT)

        assert keys_in(response) == {ATTACHMENT}

    async def test_no_note_appears_in_the_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await client.patch(
            f"/users/1/items/{LOOSE}",
            headers=WITH | {"If-Unmodified-Since-Version": "1"},
            json={"deleted": 1},
        )

        assert keys_in(await client.get("/users/1/items/trash", headers=WITH)) == {LOOSE}
        response = await client.get("/users/1/items/trash", headers=WITHOUT)

        assert keys_in(response) == set()

    async def test_a_note_is_absent_from_format_keys_and_versions(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        keys = await client.get("/users/1/items?format=keys", headers=WITHOUT)
        versions = await client.get("/users/1/items?format=versions", headers=WITHOUT)

        assert set(keys.text.split()) == {BOOK, ATTACHMENT}
        assert set(versions.json()) == {BOOK, ATTACHMENT}

    async def test_a_note_is_absent_from_an_atom_feed(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/items?format=atom", headers=WITHOUT)

        assert "confidential" not in response.text
        assert NOTE not in response.text

    async def test_num_children_does_not_count_the_hidden_note(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        """Otherwise the count is the one thing left saying a note is there."""
        narrow = await client.get(f"/users/1/items/{BOOK}", headers=WITHOUT)
        full = await client.get(f"/users/1/items/{BOOK}", headers=WITH)

        assert narrow.json()["meta"]["numChildren"] == 1
        assert full.json()["meta"]["numChildren"] == 2

    async def test_a_note_is_absent_from_a_collection_s_items(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        made = await client.post(
            "/users/1/collections",
            headers=WITH | {"If-Unmodified-Since-Version": "10"},
            json=[{"name": "Reading"}],
        )
        collection = made.json()["successful"]["0"]["key"]
        await client.patch(
            f"/users/1/items/{LOOSE}",
            headers=WITH | {"If-Unmodified-Since-Version": "1"},
            json={"collections": [collection]},
        )

        within = f"/users/1/collections/{collection}/items"
        assert keys_in(await client.get(within, headers=WITH)) == {LOOSE}
        response = await client.get(within, headers=WITHOUT)

        assert keys_in(response) == set()

    async def test_a_tag_carried_only_by_a_note_is_not_listed_within_items(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        await client.patch(
            f"/users/1/items/{LOOSE}",
            headers=WITH | {"If-Unmodified-Since-Version": "1"},
            json={"tags": [{"tag": "private"}]},
        )

        full = await client.get("/users/1/items/top/tags", headers=WITH)
        scoped = await client.get("/users/1/items/top/tags", headers=WITHOUT)

        assert "private" in [entry["tag"] for entry in full.json()]
        assert "private" not in [entry["tag"] for entry in scoped.json()]

    async def test_a_full_key_still_sees_every_note(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        """The teeth: every assertion above is about the narrow key alone."""
        listing = await client.get("/users/1/items", headers=WITH)
        single = await client.get(f"/users/1/items/{NOTE}", headers=WITH)

        assert keys_in(listing) == {BOOK, NOTE, LOOSE, ATTACHMENT}
        assert single.json()["data"]["note"] == "<p>confidential</p>"


class TestFileBytesNeedFileAccess:
    async def test_the_redirect_is_refused(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        await upload(client)

        response = await client.get(f"/users/1/items/{ATTACHMENT}/file", headers=WITHOUT)

        assert response.status_code == 403

    async def test_the_bytes_are_refused(self, client: httpx.AsyncClient, library: Library) -> None:
        await upload(client)

        response = await client.get(f"/users/1/items/{ATTACHMENT}/file/content", headers=WITHOUT)

        assert response.status_code == 403
        assert CONTENT not in response.content

    async def test_the_view_route_is_refused(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        await upload(client)

        response = await client.get(f"/users/1/items/{ATTACHMENT}/file/view", headers=WITHOUT)

        assert response.status_code == 403

    async def test_the_attachment_itself_is_still_readable(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        """Only the bytes are withheld. The item describing them is not a file."""
        await upload(client)

        response = await client.get(f"/users/1/items/{ATTACHMENT}", headers=WITHOUT)

        assert response.status_code == 200
        assert response.json()["data"]["md5"] == MD5

    async def test_a_full_key_still_downloads(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        await upload(client)

        response = await client.get(
            f"/users/1/items/{ATTACHMENT}/file", headers=WITH, follow_redirects=True
        )

        assert response.status_code == 200
        assert response.content == CONTENT
