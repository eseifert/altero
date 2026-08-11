"""Sharing one collection by link.

The longest-running request in this space -- "Share a collection, not an entire
library?" has been open since 2008 -- answered as a page rather than as sync,
because as sync it would mean lying to a client about what a library holds.
These tests hold the four things that decision rests on:

**It is not sync.** No API key reaches any of it, no library version moves when
a link is made or revoked, and nothing about a share appears in any v3 answer.

**The link decides what it reaches, and the reader cannot widen it.** The
collection and the library come out of the token; the only parameter that
narrows anything is resolved against the shared subtree, so a key from
elsewhere in the library answers 404.

**Revoked, expired, never-was and trashed are one answer.** All four are 404,
because they are the same fact from the reader's side, and telling them apart
would turn the link into a way of asking which tokens are real.

**Making one takes write access.** Giving a collection away is a decision about
the library rather than a use of it.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import CollectionShare, Library, MemberPermission, User
from altero.services import groups
from tests import factories
from tests.test_web_routes import PASSWORD, csrf_headers, register


async def sign_in_as(client: httpx.AsyncClient, session: AsyncSession, username: str) -> User:
    """Put another account on this instance and sign the browser in as it.

    Not `register`: registration closes once an account exists, so every
    account after the first arrives the way `altero user add` makes one.
    """
    from altero.services import admin, passwords

    user = await admin.create_user(session, username=username)
    user.password_hash = passwords.hash_password(PASSWORD)
    await session.commit()

    response = await client.post(
        "/web/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return user


async def personal_library(client: httpx.AsyncClient) -> int:
    return int((await client.get("/web/libraries")).json()[0]["id"])


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in, with its personal library."""
    assert (await register(client)).status_code == 201
    return client


async def make_collection(client: httpx.AsyncClient, library_id: int, name: str) -> str:
    response = await client.post(
        f"/web/libraries/{library_id}/collections",
        json={"name": name},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


async def share(
    client: httpx.AsyncClient, library_id: int, collection_key: str, **terms: object
) -> dict:
    response = await client.post(
        f"/web/libraries/{library_id}/collections/{collection_key}/shares",
        json=terms,
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def token_of(created: dict) -> str:
    """The token out of the one response that ever carries it."""
    return created["url"].rsplit("/", 1)[-1]


class TestMakingALink:
    async def test_a_link_is_made_and_answers_with_its_url_once(
        self, ada: httpx.AsyncClient
    ) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")

        created = await share(ada, library_id, key)

        assert created["url"].startswith("http://testserver/app/shared/")
        assert created["collection"] == key

    async def test_the_token_is_never_answered_again(self, ada: httpx.AsyncClient) -> None:
        """It is not stored anywhere it can be read back, and the list says so
        by not carrying it."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        await share(ada, library_id, key)

        listing = (await ada.get(f"/web/libraries/{library_id}/shares")).json()

        assert len(listing["shares"]) == 1
        assert "url" not in listing["shares"][0]
        assert "token" not in listing["shares"][0]

    async def test_no_library_version_moves(self, ada: httpx.AsyncClient) -> None:
        """A share changes no object, so telling every syncing client that
        something happened would be a lie to all of them."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        await share(ada, library_id, key)

        assert (await ada.get("/web/libraries")).json()[0]["version"] == before

    async def test_a_csrf_token_is_required(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")

        response = await ada.post(f"/web/libraries/{library_id}/collections/{key}/shares", json={})

        assert response.status_code == 403

    async def test_a_trashed_collection_cannot_be_shared(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        library = await session.get(Library, library_id)
        assert library is not None
        collection = await factories.get_collection_by_key(session, library, key)
        collection.deleted = True
        await session.commit()

        response = await ada.post(
            f"/web/libraries/{library_id}/collections/{key}/shares",
            json={},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400


class TestWhoMayShare:
    async def test_a_stranger_cannot_share_from_somebody_elses_library(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        assert (await register(client, "ada")).status_code == 201
        library_id = await personal_library(client)
        key = await make_collection(client, library_id, "Papers")
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        await sign_in_as(client, session, "grace")
        response = await client.post(
            f"/web/libraries/{library_id}/collections/{key}/shares",
            json={},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_a_read_only_group_member_cannot_share(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Giving a collection away is a decision about the library."""
        assert (await register(client, "ada")).status_code == 201
        grace = await sign_in_as(client, session, "grace")

        # Grace's group; Ada is in it and may only read.
        library = await factories.make_group(session, group_id=100, owner_id=grace.id, members={})
        collection = await factories.make_collection(session, library, key="COLLONE1")
        ada = await session.get(User, 1)
        assert ada is not None
        await groups.add_member(session, library, ada, "member", MemberPermission.READ.value)
        await session.commit()

        # …and Ada is the one asking.
        await client.post("/web/auth/logout", headers=csrf_headers(client))
        response = await client.post(
            "/web/auth/login", json={"username": "ada", "password": PASSWORD}
        )
        assert response.status_code == 200

        response = await client.post(
            f"/web/libraries/{library.id}/collections/{collection.key}/shares",
            json={},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403


class TestReadingOne:
    async def test_the_page_describes_the_collection(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        token = token_of(await share(ada, library_id, key))

        body = (await ada.get(f"/web/shared/{token}")).json()

        assert body["collection"] == "Papers"
        assert body["numItems"] == 0

    async def test_it_answers_with_no_cookie_at_all(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The point of a link: it can be sent to somebody with no account."""
        assert (await register(client, "ada")).status_code == 201
        library_id = await personal_library(client)
        key = await make_collection(client, library_id, "Papers")
        token = token_of(await share(client, library_id, key))

        client.cookies.clear()
        response = await client.get(f"/web/shared/{token}")

        assert response.status_code == 200

    async def test_the_items_of_the_collection_are_listed(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        library = await session.get(Library, library_id)
        assert library is not None
        collection = await factories.get_collection_by_key(session, library, key)
        item = await factories.make_item(session, library, fields={"title": "Inside"})
        await factories.file_item(session, collection, item)
        await factories.make_item(session, library, fields={"title": "Outside"})

        token = token_of(await share(ada, library_id, key))
        listing = (await ada.get(f"/web/shared/{token}/items")).json()

        assert [entry["data"]["title"] for entry in listing["items"]] == ["Inside"]

    async def test_the_trash_is_never_shown(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A shared collection is somebody's reading list, and what they threw
        away is not on it."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        library = await session.get(Library, library_id)
        assert library is not None
        collection = await factories.get_collection_by_key(session, library, key)
        trashed = await factories.make_item(
            session, library, fields={"title": "Gone"}, deleted=True
        )
        await factories.file_item(session, collection, trashed)

        token = token_of(await share(ada, library_id, key))
        listing = (await ada.get(f"/web/shared/{token}/items")).json()

        assert listing["items"] == []


class TestHowMuchOfTheTree:
    async def test_the_branch_comes_along_by_default(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await make_collection(ada, library_id, "Papers")
        library = await session.get(Library, library_id)
        assert library is not None
        above = await factories.get_collection_by_key(session, library, parent)
        below = await factories.make_collection(session, library, name="Drafts", parent=above)
        item = await factories.make_item(session, library, fields={"title": "Nested"})
        await factories.file_item(session, below, item)

        token = token_of(await share(ada, library_id, parent))
        listing = (await ada.get(f"/web/shared/{token}/items")).json()

        assert [entry["data"]["title"] for entry in listing["items"]] == ["Nested"]

    async def test_one_collection_alone_can_be_shared(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await make_collection(ada, library_id, "Papers")
        library = await session.get(Library, library_id)
        assert library is not None
        above = await factories.get_collection_by_key(session, library, parent)
        below = await factories.make_collection(session, library, name="Drafts", parent=above)
        item = await factories.make_item(session, library, fields={"title": "Nested"})
        await factories.file_item(session, below, item)

        token = token_of(await share(ada, library_id, parent, subcollections=False))
        listing = (await ada.get(f"/web/shared/{token}/items")).json()

        assert listing["items"] == []

    async def test_the_nested_collections_are_listed_for_the_page(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await make_collection(ada, library_id, "Papers")
        library = await session.get(Library, library_id)
        assert library is not None
        above = await factories.get_collection_by_key(session, library, parent)
        await factories.make_collection(session, library, name="Drafts", parent=above)

        token = token_of(await share(ada, library_id, parent))
        body = (await ada.get(f"/web/shared/{token}/collections")).json()

        assert [entry["data"]["name"] for entry in body["collections"]] == ["Drafts"]

    async def test_a_collection_outside_the_share_cannot_be_asked_for(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The one parameter that narrows anything is resolved against the
        subtree, so it is never a way out of it."""
        library_id = await personal_library(ada)
        shared = await make_collection(ada, library_id, "Papers")
        elsewhere = await make_collection(ada, library_id, "Private")

        token = token_of(await share(ada, library_id, shared))
        response = await ada.get(f"/web/shared/{token}/items?collection={elsewhere}")

        assert response.status_code == 404


class TestFiles:
    """Whether the bytes go is a separate answer from whether the metadata does.

    The same separation the desktop client's publishing wizard makes, and for
    the same reason: a reading list is not the same thing to hand out as the
    PDFs.
    """

    async def attach(
        self, client: httpx.AsyncClient, session: AsyncSession, library_id: int, key: str
    ) -> str:
        """An attachment in the shared collection, with real bytes behind it.

        Uploaded rather than faked, so that a 404 on the file can only be the
        link's answer -- a missing file is a 404 too, and a test that never
        stored one would pass with the rule taken out.
        """
        from altero.services import admin
        from tests.test_files import CONTENT, authorization

        api_key = (await admin.create_api_key(session, username="ada", name="seed")).key
        auth = {"Zotero-API-Key": api_key}

        created = (
            await client.post(
                "/users/1/items",
                headers=auth,
                json=[{"itemType": "attachment", "linkMode": "imported_file", "title": "Moby"}],
            )
        ).json()["successful"]["0"]

        authorized = (
            await client.post(
                f"/users/1/items/{created['key']}/file",
                headers=auth | {"If-None-Match": "*"},
                data=authorization(),
            )
        ).json()
        await client.post(authorized["url"], content=CONTENT)
        await client.post(
            f"/users/1/items/{created['key']}/file",
            headers=auth | {"If-None-Match": "*"},
            data={"upload": authorized["uploadKey"]},
        )

        library = await session.get(Library, library_id)
        assert library is not None
        collection = await factories.get_collection_by_key(session, library, key)
        item = await factories.get_item_by_key(session, library, created["key"])
        await factories.file_item(session, collection, item)
        return str(created["key"])

    async def test_a_link_that_carries_files_serves_the_bytes(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        from tests.test_files import CONTENT

        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        item_key = await self.attach(ada, session, library_id, key)

        token = token_of(await share(ada, library_id, key))
        response = await ada.get(f"/web/shared/{token}/items/{item_key}/file")

        assert response.status_code == 200
        assert response.content == CONTENT

    async def test_a_metadata_only_link_refuses_the_bytes(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        item_key = await self.attach(ada, session, library_id, key)

        token = token_of(await share(ada, library_id, key, files=False))
        response = await ada.get(f"/web/shared/{token}/items/{item_key}/file")

        assert response.status_code == 404

    async def test_the_item_is_still_described(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """An item whose PDF is not on offer still has one, and a page that hid
        it would be describing a different item than the library holds."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        item_key = await self.attach(ada, session, library_id, key)

        token = token_of(await share(ada, library_id, key, files=False))
        response = await ada.get(f"/web/shared/{token}/items/{item_key}")

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "Moby"


class TestWhenALinkStopsWorking:
    async def test_a_revoked_link_is_gone(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        created = await share(ada, library_id, key)

        assert (
            await ada.delete(f"/web/shares/{created['id']}", headers=csrf_headers(ada))
        ).status_code == 204
        assert (await ada.get(f"/web/shared/{token_of(created)}")).status_code == 404

    async def test_an_expired_link_is_gone(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        created = await share(ada, library_id, key)

        record = await session.scalar(select(CollectionShare))
        assert record is not None
        record.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        await session.commit()

        assert (await ada.get(f"/web/shared/{token_of(created)}")).status_code == 404

    async def test_a_trashed_collection_is_the_same_answer(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Somebody clearing out their library should not leave a page behind."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        created = await share(ada, library_id, key)

        library = await session.get(Library, library_id)
        assert library is not None
        collection = await factories.get_collection_by_key(session, library, key)
        collection.deleted = True
        await session.commit()

        assert (await ada.get(f"/web/shared/{token_of(created)}")).status_code == 404

    async def test_a_token_that_never_was_is_the_same_answer(
        self, client: httpx.AsyncClient
    ) -> None:
        assert (await client.get("/web/shared/nothing-like-a-real-token")).status_code == 404

    async def test_deleting_the_collection_takes_its_links(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A link to something that no longer exists must stop existing at the
        moment the thing it pointed at did."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        created = await share(ada, library_id, key)

        removed = await ada.delete(
            f"/web/libraries/{library_id}/collections/{key}", headers=csrf_headers(ada)
        )
        assert removed.status_code == 204

        assert (await ada.get(f"/web/shared/{token_of(created)}")).status_code == 404
        assert await session.scalar(select(CollectionShare)) is None

    async def test_an_expiry_in_the_past_is_refused(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")

        response = await ada.post(
            f"/web/libraries/{library_id}/collections/{key}/shares",
            json={"expires": "2000-01-01T00:00:00Z"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400


class TestChangingOne:
    async def test_the_terms_can_be_narrowed(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        created = await share(ada, library_id, key)

        response = await ada.patch(
            f"/web/shares/{created['id']}", json={"files": False}, headers=csrf_headers(ada)
        )

        assert response.status_code == 200
        assert response.json()["files"] is False

    async def test_an_expiry_can_be_cleared(self, ada: httpx.AsyncClient) -> None:
        """`null` cannot be told from "not mentioned" in a partial write, so
        clearing one is said in a word."""
        library_id = await personal_library(ada)
        key = await make_collection(ada, library_id, "Papers")
        created = await share(ada, library_id, key, expires="2099-01-01T00:00:00Z")
        assert created["expires"] is not None

        response = await ada.patch(
            f"/web/shares/{created['id']}", json={"neverExpires": True}, headers=csrf_headers(ada)
        )

        assert response.json()["expires"] is None


class TestTheV3ApiIsUntouched:
    async def test_no_key_reaches_a_share(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The whole reason this is a page and not a permission."""
        await factories.make_user(session)
        await factories.make_api_key(session, key="P9NiFoyLeZu2bZNvvuQPDWsd")

        for path in ("/web/libraries/1/shares", "/web/shares/1"):
            response = await client.get(
                path, headers={"Zotero-API-Key": "P9NiFoyLeZu2bZNvvuQPDWsd"}
            )
            assert response.status_code in (401, 403, 405), path
