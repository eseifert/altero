"""Putting a file into a library from the browser.

Two doors: one makes a new attachment holding the file, standalone or under an
item; the other puts new bytes on an attachment that already has a file. Both
take the file as the request body, are held to the same rules as the v3 upload
-- the group's ``fileEditing`` policy, the member's own permission, the size
limit, the digest the store is addressed by -- and end in the object a desktop
upload would have left: the item at one new library version, its ``md5``,
``mtime`` and ``filename`` describing bytes any client can download.
"""

import hashlib
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from altero.api.deps import get_upload_limit
from altero.models import Group, Library, MemberPermission, User
from altero.services import admin, groups, storage
from altero.settings import Settings
from tests import factories
from tests.test_web_items import make_collection, personal_library, seed_item
from tests.test_web_routes import csrf_headers, register

CONTENT = b"%PDF-1.7\nnot much of a paper, but bytes nonetheless\n"
MD5 = hashlib.md5(CONTENT).hexdigest()

#: 2026-10-27, the moment the file was last changed on somebody's disk.
MTIME = 1793120000000


@pytest.fixture
async def ada(client: httpx2.AsyncClient) -> httpx2.AsyncClient:
    """One account, signed in, with its personal library."""
    assert (await register(client)).status_code == 201
    return client


def upload_headers(
    client: httpx2.AsyncClient, content_type: str = "application/pdf", **more: str
) -> dict[str, str]:
    return {**csrf_headers(client), "Content-Type": content_type, **more}


async def upload(
    client: httpx2.AsyncClient,
    library_id: int,
    content: bytes = CONTENT,
    *,
    content_type: str = "application/pdf",
    **query: Any,
) -> httpx2.Response:
    params: dict[str, Any] = {"filename": "paper.pdf", "mtime": MTIME, **query}
    return await client.post(
        f"/web/libraries/{library_id}/attachments",
        params=params,
        content=content,
        headers=upload_headers(client, content_type),
    )


async def library_version(client: httpx2.AsyncClient, library_id: int) -> int:
    response = await client.get(f"/web/libraries/{library_id}/items")
    return int(response.json()["libraryVersion"])


async def downloaded(client: httpx2.AsyncClient, library_id: int, key: str) -> bytes:
    response = await client.get(f"/web/libraries/{library_id}/items/{key}/file")
    assert response.status_code == 200
    return response.content


def stored_files(settings: Settings) -> list[str]:
    """Every file under the store, staging files included."""
    root = settings.storage_path
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


async def group_with_ada(
    session: AsyncSession,
    *,
    permission: str = MemberPermission.INHERIT.value,
    file_editing: str = "members",
    role: str = "member",
) -> Library:
    """A group of Grace's in which Ada is a member."""
    grace = await admin.create_user(session, username="grace")
    group = await factories.make_group(session, group_id=60, owner_id=grace.id, members={1: role})
    policy = await session.get(Group, group.id)
    assert policy is not None
    policy.file_editing = file_editing
    if permission != MemberPermission.INHERIT.value:
        ada = await session.get(User, 1)
        assert ada is not None
        await groups.set_permission(session, group, ada, permission)
    await session.commit()
    return group


class TestANewAttachment:
    async def test_a_file_becomes_a_child_attachment(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)

        response = await upload(ada, library_id, parentItem=parent, title="PDF")

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["itemType"] == "attachment"
        assert data["linkMode"] == "imported_file"
        assert data["parentItem"] == parent
        assert data["title"] == "PDF"
        assert data["filename"] == "paper.pdf"
        assert data["contentType"] == "application/pdf"
        assert data["md5"] == MD5
        assert data["mtime"] == MTIME
        assert await downloaded(ada, library_id, data["key"]) == CONTENT

    async def test_a_standalone_file_is_filed_where_it_was_dropped(
        self, ada: httpx2.AsyncClient
    ) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")

        response = await upload(ada, library_id, collections=papers)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["collections"] == [papers]
        assert "parentItem" not in data

    async def test_it_takes_one_version(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)
        before = await library_version(ada, library_id)

        response = await upload(ada, library_id)

        assert response.status_code == 201
        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert response.json()["version"] == before + 1
        assert await library_version(ada, library_id) == before + 1

    async def test_a_desktop_downloads_it_the_way_it_downloads_its_own(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        """The same stored object: the v3 redirect describes it and serves it."""
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id)).json()["key"]
        api_key = await admin.create_api_key(session, username="ada", name="laptop")

        redirect = await ada.get(
            f"/users/1/items/{key}/file", headers={"Zotero-API-Key": api_key.key}
        )

        assert redirect.status_code == 302
        assert redirect.headers["Zotero-File-MD5"] == MD5
        assert redirect.headers["Zotero-File-Modification-Time"] == str(MTIME)
        assert redirect.headers["Zotero-File-Compressed"] == "No"
        served = await ada.get(redirect.headers["Location"])
        assert served.content == CONTENT

    async def test_without_a_title_it_is_named_after_the_file(
        self, ada: httpx2.AsyncClient
    ) -> None:
        """The desktop's fallback in `setAutoAttachmentTitle`: the name, less its extension."""
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, filename="Smith 2024.final.pdf")

        assert response.json()["data"]["title"] == "Smith 2024.final"

    async def test_a_file_name_is_made_valid_as_the_desktop_makes_it(
        self, ada: httpx2.AsyncClient
    ) -> None:
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, filename='../a/b:c?"d".pdf')

        assert response.json()["data"]["filename"] == ".abcd.pdf"

    async def test_a_name_with_nothing_left_is_an_underscore(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, filename="/")

        assert response.json()["data"]["filename"] == "_"

    async def test_without_a_name_it_is_refused(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/attachments",
            content=CONTENT,
            headers=upload_headers(ada),
        )

        assert response.status_code == 400

    async def test_an_unknown_type_is_guessed_from_the_name(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await upload(
            ada,
            library_id,
            b"<html></html>",
            content_type="application/octet-stream",
            filename="page.html",
        )

        assert response.json()["data"]["contentType"] == "text/html"

    async def test_a_charset_comes_with_the_type(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await upload(
            ada,
            library_id,
            b"plain words",
            content_type="text/plain; charset=UTF-8",
            filename="words.txt",
        )

        data = response.json()["data"]
        assert data["contentType"] == "text/plain"
        assert data["charset"] == "utf-8"

    async def test_a_file_already_stored_is_attached_without_storing_it_twice(
        self, ada: httpx2.AsyncClient, settings: Settings
    ) -> None:
        library_id = await personal_library(ada)
        first = (await upload(ada, library_id)).json()["key"]

        second = (await upload(ada, library_id, filename="again.pdf")).json()["key"]

        assert first != second
        assert stored_files(settings) == [f"{MD5[:2]}/{MD5}"]
        assert await downloaded(ada, library_id, second) == CONTENT

    async def test_an_empty_file_is_a_file(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, b"", filename="empty.txt")

        assert response.status_code == 201
        assert response.json()["data"]["md5"] == hashlib.md5(b"").hexdigest()

    async def test_a_form_is_refused_rather_than_stored(
        self, ada: httpx2.AsyncClient, settings: Settings
    ) -> None:
        """A form's boundary and headers stored as the file would be a corrupt file."""
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, content_type="multipart/form-data; boundary=x")

        assert response.status_code == 400
        assert stored_files(settings) == []


class TestWhereANewAttachmentGoes:
    async def test_a_note_cannot_hold_one(
        self, ada: httpx2.AsyncClient, session: AsyncSession, settings: Settings
    ) -> None:
        library_id = await personal_library(ada)
        library = await session.get(Library, library_id)
        assert library is not None
        note = await factories.make_item(session, library, item_type="note")
        await session.commit()

        response = await upload(ada, library_id, parentItem=note.key)

        assert response.status_code == 400
        assert stored_files(settings) == []

    async def test_a_child_cannot_hold_one(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        library = await session.get(Library, library_id)
        assert library is not None
        book = await factories.make_item(session, library)
        attachment = await factories.make_item(
            session,
            library,
            item_type="attachment",
            parent=book,
            fields={"linkMode": "imported_file"},
        )
        await session.commit()

        response = await upload(ada, library_id, parentItem=attachment.key)

        assert response.status_code == 400

    async def test_a_trashed_parent_is_refused(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        library = await session.get(Library, library_id)
        assert library is not None
        book = await factories.make_item(session, library, deleted=True)
        await session.commit()

        response = await upload(ada, library_id, parentItem=book.key)

        assert response.status_code == 400

    async def test_an_unknown_parent_is_not_found(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, parentItem="ABCD2345")

        assert response.status_code == 404

    async def test_a_child_is_not_filed(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        """A child sits in its parent's collections; the desktop refuses both at once."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        parent = await seed_item(ada, session)

        response = await upload(ada, library_id, parentItem=parent, collections=papers)

        assert response.status_code == 400

    async def test_an_unknown_collection_is_not_found(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await upload(ada, library_id, collections="ABCD2345")

        assert response.status_code == 404


class TestWhatChangesWhileTheFileArrives:
    """The permissions are asked before the body is read and again under the lock.

    Between the two, a large file can take minutes, and the answer that counts
    is the later one.
    """

    async def test_a_parent_trashed_meanwhile_is_refused(
        self,
        ada: httpx2.AsyncClient,
        session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)
        before = await library_version(ada, library_id)
        meanwhile(monkeypatch, session, f"UPDATE items SET deleted = 1 WHERE key = '{parent}'")

        response = await upload(ada, library_id, parentItem=parent)

        assert response.status_code == 400, response.text
        assert "trash" in response.json()["message"], response.text
        assert await library_version(ada, library_id) == before

    async def test_a_file_replaced_meanwhile_is_not_overwritten(
        self,
        ada: httpx2.AsyncClient,
        session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id)).json()["key"]
        other = "e" * 32
        meanwhile(
            monkeypatch,
            session,
            "UPDATE item_fields SET value = '" + other + "' WHERE field = 'md5' AND item_id = "
            f"(SELECT id FROM items WHERE key = '{key}')",
        )

        response = await replace(ada, library_id, key)

        assert response.status_code == 412


def meanwhile(monkeypatch: pytest.MonkeyPatch, session: AsyncSession, statement: str) -> None:
    """Have another writer run ``statement`` while the upload's bytes arrive."""
    receive = storage.receive_bytes

    async def receiving(*args: Any, **kwargs: Any) -> tuple[str, int]:
        await session.execute(text(statement))
        await session.commit()
        return await receive(*args, **kwargs)

    monkeypatch.setattr(storage, "receive_bytes", receiving)


class TestWhoMayUpload:
    async def test_it_needs_the_csrf_token(
        self, ada: httpx2.AsyncClient, settings: Settings
    ) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/attachments",
            params={"filename": "paper.pdf"},
            content=CONTENT,
            headers={"Content-Type": "application/pdf"},
        )

        assert response.status_code == 403
        assert stored_files(settings) == []

    async def test_an_api_key_does_not_open_this_door(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        ada.cookies.clear()

        response = await ada.post(
            f"/web/libraries/{library_id}/attachments",
            params={"filename": "paper.pdf"},
            content=CONTENT,
            headers={"Zotero-API-Key": key.key, "X-CSRF-Token": "anything"},
        )

        assert response.status_code == 401

    async def test_somebody_elses_library_is_refused_unread(
        self, ada: httpx2.AsyncClient, session: AsyncSession, settings: Settings
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None

        response = await upload(ada, theirs.id)

        assert response.status_code == 403
        assert stored_files(settings) == []

    async def test_a_member_held_to_reading_is_refused(
        self, ada: httpx2.AsyncClient, session: AsyncSession, settings: Settings
    ) -> None:
        group = await group_with_ada(session, permission=MemberPermission.READ.value)

        response = await upload(ada, group.id)

        assert response.status_code == 403
        assert stored_files(settings) == []

    async def test_a_group_without_files_refuses_its_members(
        self, ada: httpx2.AsyncClient, session: AsyncSession, settings: Settings
    ) -> None:
        group = await group_with_ada(session, file_editing="none")

        response = await upload(ada, group.id)

        assert response.status_code == 403
        assert stored_files(settings) == []

    async def test_a_group_keeping_files_to_admins_refuses_a_member(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        group = await group_with_ada(session, file_editing="admins")

        response = await upload(ada, group.id)

        assert response.status_code == 403

    async def test_a_group_keeping_files_to_admins_takes_an_admins(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        group = await group_with_ada(session, file_editing="admins", role="admin")

        response = await upload(ada, group.id)

        assert response.status_code == 201

    async def test_a_member_held_to_adding_may_add_one(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        group = await group_with_ada(session, permission=MemberPermission.ADD.value)

        response = await upload(ada, group.id)

        assert response.status_code == 201


class TestTheSizeLimit:
    @pytest.fixture
    def ten_bytes(self, app: FastAPI) -> Any:
        app.dependency_overrides[get_upload_limit] = lambda: 10
        yield
        app.dependency_overrides.pop(get_upload_limit)

    async def test_a_declared_size_over_it_is_refused_unread(
        self, ada: httpx2.AsyncClient, settings: Settings, ten_bytes: None
    ) -> None:
        library_id = await personal_library(ada)
        sent: list[bytes] = []

        async def body() -> Any:
            # Each chunk under the limit, so only the declared length can refuse it this early.
            for index in range(0, len(CONTENT), 4):
                sent.append(CONTENT[index : index + 4])
                yield CONTENT[index : index + 4]

        response = await ada.post(
            f"/web/libraries/{library_id}/attachments",
            params={"filename": "paper.pdf"},
            content=body(),
            headers=upload_headers(ada, **{"Content-Length": str(len(CONTENT))}),
        )

        assert response.status_code == 413
        assert len(sent) <= 1
        assert stored_files(settings) == []

    async def test_a_stream_past_it_is_cut_off_and_leaves_nothing(
        self, ada: httpx2.AsyncClient, settings: Settings, ten_bytes: None
    ) -> None:
        library_id = await personal_library(ada)

        async def body() -> Any:
            for index in range(0, len(CONTENT), 4):
                yield CONTENT[index : index + 4]

        response = await ada.post(
            f"/web/libraries/{library_id}/attachments",
            params={"filename": "paper.pdf"},
            content=body(),
            headers=upload_headers(ada),
        )

        assert response.status_code == 413
        assert stored_files(settings) == []
        assert await library_version(ada, library_id) == 0

    def test_it_is_a_setting(self, tmp_path: Any) -> None:
        assert Settings(max_upload_mb=5).max_upload_bytes == 5 * 1024 * 1024
        assert Settings().max_upload_bytes == 1024 * 1024 * 1024


NEW = b"%PDF-1.7\nthe second draft, which is better\n"
NEW_MD5 = hashlib.md5(NEW).hexdigest()


async def replace(
    client: httpx2.AsyncClient,
    library_id: int,
    key: str,
    content: bytes = NEW,
    *,
    if_match: str | None = MD5,
    content_type: str = "application/pdf",
    **query: Any,
) -> httpx2.Response:
    headers = upload_headers(client, content_type)
    if if_match is not None:
        headers["If-Match"] = if_match
    params: dict[str, Any] = {"filename": "paper-v2.pdf", "mtime": MTIME + 1000, **query}
    return await client.put(
        f"/web/libraries/{library_id}/items/{key}/file",
        params=params,
        content=content,
        headers=headers,
    )


class TestReplacingAFile:
    async def test_the_attachment_takes_the_new_bytes(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id, title="Draft")).json()["key"]
        before = await library_version(ada, library_id)

        response = await replace(ada, library_id, key)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["md5"] == NEW_MD5
        assert data["mtime"] == MTIME + 1000
        assert data["filename"] == "paper-v2.pdf"
        assert data["title"] == "Draft"
        assert data["version"] == before + 1
        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert await downloaded(ada, library_id, key) == NEW

    async def test_a_stale_digest_is_refused(
        self, ada: httpx2.AsyncClient, settings: Settings
    ) -> None:
        """The precondition the v3 upload takes: another client replaced it first."""
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id)).json()["key"]

        response = await replace(ada, library_id, key, if_match="0" * 32)

        assert response.status_code == 412
        assert await downloaded(ada, library_id, key) == CONTENT
        assert stored_files(settings) == [f"{MD5[:2]}/{MD5}"]

    async def test_without_a_precondition_it_is_refused(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id)).json()["key"]

        response = await replace(ada, library_id, key, if_match=None)

        assert response.status_code == 428

    async def test_missing_bytes_are_replaced_on_none_match(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        """A migrated attachment naming a digest nothing here backs."""
        library_id = await personal_library(ada)
        library = await session.get(Library, library_id)
        assert library is not None
        item = await factories.make_item(
            session,
            library,
            item_type="attachment",
            fields={"linkMode": "imported_file", "md5": "f" * 32, "filename": "gone.pdf"},
        )
        await session.commit()

        response = await ada.put(
            f"/web/libraries/{library_id}/items/{item.key}/file",
            params={"filename": "found.pdf"},
            content=NEW,
            headers=upload_headers(ada, **{"If-None-Match": "*"}),
        )

        assert response.status_code == 200
        assert await downloaded(ada, library_id, item.key) == NEW

    async def test_a_linked_file_is_refused(
        self, ada: httpx2.AsyncClient, session: AsyncSession, settings: Settings
    ) -> None:
        library_id = await personal_library(ada)
        library = await session.get(Library, library_id)
        assert library is not None
        item = await factories.make_item(
            session,
            library,
            item_type="attachment",
            fields={"linkMode": "linked_file", "path": "/home/ada/paper.pdf"},
        )
        await session.commit()

        response = await replace(ada, library_id, item.key, if_match=None)

        assert response.status_code == 400
        assert stored_files(settings) == []

    async def test_a_regular_item_is_refused(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        book = await seed_item(ada, session)

        response = await replace(ada, library_id, book)

        assert response.status_code == 400

    async def test_a_trashed_attachment_is_refused(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id)).json()["key"]
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [key], "deleted": True},
            headers=csrf_headers(ada),
        )

        response = await replace(ada, library_id, key)

        assert response.status_code == 400
        assert await downloaded(ada, library_id, key) == CONTENT

    async def test_it_needs_the_csrf_token(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = (await upload(ada, library_id)).json()["key"]

        response = await ada.put(
            f"/web/libraries/{library_id}/items/{key}/file",
            params={"filename": "paper.pdf"},
            content=NEW,
            headers={"Content-Type": "application/pdf", "If-Match": MD5},
        )

        assert response.status_code == 403
        assert await downloaded(ada, library_id, key) == CONTENT

    async def test_a_member_held_to_their_own_cannot_replace_somebody_elses(
        self, ada: httpx2.AsyncClient, session: AsyncSession, settings: Settings
    ) -> None:
        group = await group_with_ada(session, permission=MemberPermission.OWN.value)
        item = await factories.make_item(
            session,
            group,
            item_type="attachment",
            fields={"linkMode": "imported_file", "md5": MD5, "filename": "theirs.pdf"},
        )
        await session.commit()

        response = await replace(ada, group.id, item.key)

        assert response.status_code == 403
        assert stored_files(settings) == []

    async def test_a_group_without_files_refuses_it(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        group = await group_with_ada(session, file_editing="none")
        item = await factories.make_item(
            session,
            group,
            item_type="attachment",
            fields={"linkMode": "imported_file", "md5": MD5, "filename": "ours.pdf"},
        )
        await session.commit()

        response = await replace(ada, group.id, item.key)

        assert response.status_code == 403


async def link(client: httpx2.AsyncClient, library_id: int, **body: Any) -> httpx2.Response:
    return await client.post(
        f"/web/libraries/{library_id}/items",
        json={"itemType": "attachment", "linkMode": "linked_url", **body},
        headers=csrf_headers(client),
    )


class TestAWebLink:
    """The desktop's *Attach Web Link…*: a `linked_url` attachment, made by P1.2's route."""

    async def test_a_link_is_attached_with_its_title(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)

        response = await link(
            ada, library_id, parentItem=parent, url="https://example.org/a", title="The paper"
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["linkMode"] == "linked_url"
        assert data["parentItem"] == parent
        assert data["url"] == "https://example.org/a"
        assert data["title"] == "The paper"
        assert "md5" not in data

    @pytest.mark.parametrize(
        ("url", "title"),
        [
            ("https://example.org/", "example.org"),
            ("https://example.org/papers/smith.pdf?download=1#page=2", "smith.pdf"),
            ("https://example.org/papers/smith/", "smith"),
            ("ftp://example.org/papers/smith.pdf", "ftp://example.org/papers/smith.pdf"),
        ],
    )
    async def test_without_a_title_it_is_named_after_the_address(
        self, ada: httpx2.AsyncClient, url: str, title: str
    ) -> None:
        """`Zotero.Attachments.linkFromURL`: a web path's last part, else the host or the URL."""
        library_id = await personal_library(ada)

        response = await link(ada, library_id, url=url)

        assert response.json()["data"]["title"] == title

    async def test_a_pdf_address_is_a_pdf(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await link(ada, library_id, url="https://example.org/Smith.PDF")

        assert response.json()["data"]["contentType"] == "application/pdf"

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///home/ada/paper.pdf",
            "mailto:ada@example.org",
            "example.org",
            "",
        ],
    )
    async def test_an_address_the_desktop_would_not_link_is_refused(
        self, ada: httpx2.AsyncClient, url: str
    ) -> None:
        library_id = await personal_library(ada)

        response = await link(ada, library_id, url=url)

        assert response.status_code == 400
        assert (await ada.get(f"/web/libraries/{library_id}/items")).json()["items"] == []

    async def test_a_file_attachment_is_not_made_this_way(self, ada: httpx2.AsyncClient) -> None:
        """A stored file comes with its bytes, through the upload."""
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/items",
            json={"itemType": "attachment", "linkMode": "imported_file"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400

    async def test_a_note_cannot_hold_one(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        library = await session.get(Library, library_id)
        assert library is not None
        note = await factories.make_item(session, library, item_type="note")
        await session.commit()

        response = await link(ada, library_id, parentItem=note.key, url="https://example.org")

        assert response.status_code == 400

    async def test_a_group_without_files_still_takes_one(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        """A link holds no file: the desktop offers it where files are not allowed."""
        group = await group_with_ada(session, file_editing="none")

        response = await link(ada, group.id, url="https://example.org")

        assert response.status_code == 201


class TestWhatTheInterfaceIsTold:
    async def summary(self, client: httpx2.AsyncClient, library_id: int) -> dict[str, Any]:
        listed = (await client.get("/web/libraries")).json()
        return next(entry for entry in listed if entry["id"] == library_id)

    async def test_ones_own_library_takes_files(self, ada: httpx2.AsyncClient) -> None:
        library_id = await personal_library(ada)

        assert (await self.summary(ada, library_id))["filesEditable"] is True

    @pytest.mark.parametrize(
        ("file_editing", "role", "editable"),
        [
            ("members", "member", True),
            ("admins", "member", False),
            ("admins", "admin", True),
            ("none", "admin", False),
        ],
    )
    async def test_a_group_says_by_its_policy(
        self,
        ada: httpx2.AsyncClient,
        session: AsyncSession,
        file_editing: str,
        role: str,
        editable: bool,
    ) -> None:
        group = await group_with_ada(session, file_editing=file_editing, role=role)

        assert (await self.summary(ada, group.id))["filesEditable"] is editable

    async def test_a_reader_is_told_no(
        self, ada: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        group = await group_with_ada(session, permission=MemberPermission.READ.value)

        assert (await self.summary(ada, group.id))["filesEditable"] is False

    async def test_and_the_largest_file(self, ada: httpx2.AsyncClient, app: FastAPI) -> None:
        app.dependency_overrides[get_upload_limit] = lambda: 10
        library_id = await personal_library(ada)

        assert (await self.summary(ada, library_id))["maxUploadBytes"] == 10
