"""Exporting and restoring a library through the browser.

The transfer itself is tested against the service in ``test_transfer.py``, in
full and by comparison: what is checked here is the door the browser goes
through. That door is the only place in ``/web`` where the interface writes to a
library rather than reading one, and it writes wholesale, so what matters is who
it opens for and what it refuses:

- the archive is built for the library the *session* names, not the one the
  uploaded file names;
- a restore takes the account password, and does nothing without it;
- a library with anything in it is not merged into.
"""

import io
import json
import zipfile

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library, LibraryType, User
from altero.services import passwords, transfer
from tests import factories

PASSWORD = "correct horse battery"


async def sign_up(client: httpx.AsyncClient, username: str = "ada") -> httpx.Response:
    return await client.post(
        "/web/auth/register",
        json={"username": username, "password": PASSWORD, "email": f"{username}@example.org"},
    )


async def sign_in(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/web/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["altero_csrf"]}


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in. The first registration is always allowed."""
    assert (await sign_up(client)).status_code == 201
    return client


async def personal(session: AsyncSession, owner_id: int) -> Library:
    library = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == owner_id)
    )
    assert library is not None
    return library


async def seed(session: AsyncSession, library: Library, title: str) -> None:
    """Put one item in a library and move its version on, as a write would."""
    await factories.make_item(session, library, fields={"title": title}, version=7)
    library.version = 7
    await session.commit()


async def make_signed_in(
    session: AsyncSession, client: httpx.AsyncClient, user_id: int, username: str
) -> User:
    """A second account, with a password, signed in on ``client``."""
    user = await factories.make_user(session, user_id=user_id, username=username)
    user.password_hash = passwords.hash_password(PASSWORD)
    user.email = f"{username}@example.org"
    await session.commit()
    await client.post("/web/auth/logout", headers=csrf(client))
    await sign_in(client, username)
    return user


def archive_of(response: httpx.Response) -> dict:
    """Return the manifest of the archive in a response body."""
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        return json.loads(bundle.read(transfer.MANIFEST))


def upload(content: bytes, **fields: str) -> dict:
    """The multipart body the browser sends, as httpx wants it."""
    return {
        "files": {"archive": ("library.zip", content, "application/zip")},
        "data": {"currentPassword": PASSWORD, **fields},
    }


class TestExport:
    async def test_the_personal_library_comes_back_as_an_archive(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal(session, 1)
        await seed(session, library, "Structure and Interpretation")

        response = await ada.get(f"/web/libraries/{library.id}/archive")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "altero-user-1.zip" in response.headers["content-disposition"]
        assert archive_of(response)["counts"]["items"] == 1

    async def test_it_needs_a_session(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await sign_up(client)
        library = await personal(session, 1)
        client.cookies.clear()

        assert (await client.get(f"/web/libraries/{library.id}/archive")).status_code == 401

    async def test_another_account_s_library_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        mine = await personal(session, 1)
        await make_signed_in(session, ada, 2, "grace")

        response = await ada.get(f"/web/libraries/{mine.id}/archive")

        assert response.status_code == 403

    async def test_a_missing_library_is_404(self, ada: httpx.AsyncClient) -> None:
        assert (await ada.get("/web/libraries/9999/archive")).status_code == 404

    async def test_a_group_administrator_may_export_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        await factories.make_user(session, user_id=2, username="grace")
        await factories.add_group_member(session, library_id=group["id"], user_id=2, role="admin")
        await make_signed_in_existing(session, ada, "grace")

        response = await ada.get(f"/web/libraries/{group['id']}/archive")

        assert response.status_code == 200

    async def test_a_plain_member_may_not(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Reading the library item by item is one thing; being handed the
        whole of it, deletion log and files included, is an administrator's."""
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        await factories.make_user(session, user_id=2, username="grace")
        await factories.add_group_member(session, library_id=group["id"], user_id=2)
        await make_signed_in_existing(session, ada, "grace")

        response = await ada.get(f"/web/libraries/{group['id']}/archive")

        assert response.status_code == 403


async def make_signed_in_existing(
    session: AsyncSession, client: httpx.AsyncClient, username: str
) -> None:
    """Give an already-created account a password and sign it in."""
    user = await session.scalar(select(User).where(User.username == username))
    assert user is not None
    user.password_hash = passwords.hash_password(PASSWORD)
    user.email = f"{username}@example.org"
    await session.commit()
    await client.post("/web/auth/logout", headers=csrf(client))
    await sign_in(client, username)


class TestRestore:
    async def test_an_archive_goes_back_into_the_library_it_came_from(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal(session, 1)
        await seed(session, library, "Structure and Interpretation")
        content = (await ada.get(f"/web/libraries/{library.id}/archive")).content

        response = await ada.post(
            f"/web/libraries/{library.id}/archive",
            headers=csrf(ada),
            **upload(content, replace="true"),
        )

        assert response.status_code == 200, response.text
        assert response.json()["counts"]["items"] == 1
        # The version clients remember, restored rather than renumbered.
        assert response.json()["library"]["version"] == 7
        titles = await ada.get(f"/web/libraries/{library.id}/items")
        assert [item["data"]["title"] for item in titles.json()["items"]] == [
            "Structure and Interpretation"
        ]

    async def test_the_uploaded_file_does_not_choose_the_library(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The heart of it. An archive names a library in its manifest, and the
        command line trusts that name. Here the session decides instead: an
        archive of somebody else's library restores into *your* library or
        nowhere, and theirs is left alone."""
        theirs = await personal(session, 1)
        theirs_id = theirs.id
        await seed(session, theirs, "Ada's book")
        content = (await ada.get(f"/web/libraries/{theirs_id}/archive")).content
        assert archive_of(httpx.Response(200, content=content))["library"]["id"] == 1

        await make_signed_in(session, ada, 2, "grace")
        mine = await personal(session, 2)

        response = await ada.post(
            f"/web/libraries/{mine.id}/archive", headers=csrf(ada), **upload(content)
        )

        assert response.status_code == 200, response.text
        assert response.json()["library"]["ownerId"] == 2
        assert response.json()["source"]["ownerId"] == 1
        # Ada's own library still holds exactly what it held. Expired first:
        # the restore went through the request's own session, and this one is
        # still holding what it read before that.
        session.expire_all()
        held = await session.scalars(select(Item).where(Item.library_id == theirs_id))
        assert [item.field_values()["title"] for item in held] == ["Ada's book"]

    async def test_restoring_into_another_account_s_library_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        theirs = await personal(session, 1)
        content = (await ada.get(f"/web/libraries/{theirs.id}/archive")).content
        await make_signed_in(session, ada, 2, "grace")

        response = await ada.post(
            f"/web/libraries/{theirs.id}/archive", headers=csrf(ada), **upload(content)
        )

        assert response.status_code == 403

    async def test_the_password_is_required(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal(session, 1)
        library_id = library.id
        await seed(session, library, "Structure and Interpretation")
        content = (await ada.get(f"/web/libraries/{library_id}/archive")).content

        response = await ada.post(
            f"/web/libraries/{library_id}/archive",
            headers=csrf(ada),
            files={"archive": ("library.zip", content, "application/zip")},
            data={"currentPassword": "not it", "replace": "true"},
        )

        assert response.status_code == 403
        session.expire_all()
        # And the library it would have replaced is untouched.
        held = await session.scalars(select(Item).where(Item.library_id == library_id))
        assert len(list(held)) == 1

    async def test_it_needs_the_csrf_header(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal(session, 1)
        content = (await ada.get(f"/web/libraries/{library.id}/archive")).content

        response = await ada.post(f"/web/libraries/{library.id}/archive", **upload(content))

        assert response.status_code == 403

    async def test_a_library_with_objects_in_it_is_not_merged_into(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal(session, 1)
        await seed(session, library, "Structure and Interpretation")
        content = (await ada.get(f"/web/libraries/{library.id}/archive")).content

        response = await ada.post(
            f"/web/libraries/{library.id}/archive", headers=csrf(ada), **upload(content)
        )

        assert response.status_code == 400
        assert "not empty" in response.json()["message"]

    async def test_something_that_is_not_an_archive_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await personal(session, 1)

        response = await ada.post(
            f"/web/libraries/{library.id}/archive",
            headers=csrf(ada),
            **upload(b"not a zip at all"),
        )

        assert response.status_code == 400
        assert "not an altero library archive" in response.json()["message"]

    async def test_a_group_administrator_may_not_restore_over_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Only the owner: a restore ends the library as its members knew it,
        which is what deleting the group does and is held to the same person."""
        group = (await ada.post("/web/groups", json={"name": "Engine"}, headers=csrf(ada))).json()
        content = (await ada.get(f"/web/libraries/{group['id']}/archive")).content
        await factories.make_user(session, user_id=2, username="grace")
        await factories.add_group_member(session, library_id=group["id"], user_id=2, role="admin")
        await make_signed_in_existing(session, ada, "grace")

        response = await ada.post(
            f"/web/libraries/{group['id']}/archive", headers=csrf(ada), **upload(content)
        )

        assert response.status_code == 403


class TestTheSyncApiCannotReachIt:
    async def test_an_api_key_does_not_open_the_archive(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The boundary in both directions, as everywhere else under /web."""
        from altero.services import admin

        library = await personal(session, 1)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        ada.cookies.clear()

        response = await ada.get(
            f"/web/libraries/{library.id}/archive", headers={"Zotero-API-Key": key.key}
        )

        assert response.status_code == 401
