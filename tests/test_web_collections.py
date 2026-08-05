"""Making and removing collections through the browser.

The write itself is `services/objectwrites`, tested against the v3 endpoints in
``test_objects_write.py``. What is checked here is what only this door has: a
cookie instead of a key, a CSRF token, who may write to which library, and the
version counter moving exactly once per request.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Collection, Library
from altero.services import admin
from tests import factories
from tests.test_web_routes import csrf_headers, register


async def personal_library(client: httpx.AsyncClient) -> int:
    return int((await client.get("/web/libraries")).json()[0]["id"])


async def collection_names(client: httpx.AsyncClient, library_id: int) -> list[str]:
    payload = (await client.get(f"/web/libraries/{library_id}/collections")).json()
    return [entry["data"]["name"] for entry in payload["collections"]]


@pytest.fixture
async def ada(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """One account, signed in, with its personal library."""
    assert (await register(client)).status_code == 201
    return client


class TestMakingOne:
    async def test_a_collection_is_made_and_listed(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "Papers"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 201
        assert response.json()["data"]["name"] == "Papers"
        assert await collection_names(ada, library_id) == ["Papers"]

    async def test_it_comes_back_in_the_shape_the_sidebar_reads(
        self, ada: httpx.AsyncClient
    ) -> None:
        """The same envelope as the listing, so nothing has to be built twice."""
        library_id = await personal_library(ada)

        body = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["key"]
        assert body["version"] >= 1
        assert body["data"]["parentCollection"] is False
        assert body["meta"] == {"numCollections": 0, "numItems": 0}

    async def test_a_subcollection_names_its_parent(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        parent = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()

        child = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Unread", "parentCollection": parent["key"]},
                headers=csrf_headers(ada),
            )
        ).json()

        assert child["data"]["parentCollection"] == parent["key"]
        listed = (await ada.get(f"/web/libraries/{library_id}/collections")).json()["collections"]
        assert next(e for e in listed if e["key"] == parent["key"])["meta"]["numCollections"] == 1

    async def test_a_parent_in_another_library_is_not_found(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Otherwise it would silently become a top-level collection here."""
        library_id = await personal_library(ada)
        elsewhere = await factories.make_library(session, owner_id=99)
        stray = await factories.make_collection(session, library=elsewhere, name="Theirs")

        response = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "Unread", "parentCollection": stray.key},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 404
        assert await collection_names(ada, library_id) == []

    async def test_an_empty_name_is_refused(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "   "},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400
        assert await collection_names(ada, library_id) == []

    async def test_the_name_is_trimmed(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "  Papers  "},
            headers=csrf_headers(ada),
        )

        assert await collection_names(ada, library_id) == ["Papers"]

    async def test_an_absurd_name_is_refused(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "x" * 256},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400


class TestRemovingOne:
    async def test_a_collection_is_removed(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        made = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()

        response = await ada.delete(
            f"/web/libraries/{library_id}/collections/{made['key']}", headers=csrf_headers(ada)
        )

        assert response.status_code == 204
        assert await collection_names(ada, library_id) == []

    async def test_its_items_stay_in_the_library(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Deleting a collection is not deleting what was filed in it."""
        library_id = await personal_library(ada)
        key = await admin.create_api_key(session, username="ada", name="seed")
        made = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()
        await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "book", "title": "Filed", "collections": [made["key"]]}],
        )

        await ada.delete(
            f"/web/libraries/{library_id}/collections/{made['key']}", headers=csrf_headers(ada)
        )

        items = (await ada.get(f"/web/libraries/{library_id}/items")).json()
        assert [item["data"]["title"] for item in items["items"]] == ["Filed"]

    async def test_subcollections_move_up_rather_than_disappear(
        self, ada: httpx.AsyncClient
    ) -> None:
        """The v3 delete promotes them, and there is one behaviour, not two."""
        library_id = await personal_library(ada)
        parent = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()
        await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "Unread", "parentCollection": parent["key"]},
            headers=csrf_headers(ada),
        )

        await ada.delete(
            f"/web/libraries/{library_id}/collections/{parent['key']}", headers=csrf_headers(ada)
        )

        listed = (await ada.get(f"/web/libraries/{library_id}/collections")).json()["collections"]
        assert [(e["data"]["name"], e["data"]["parentCollection"]) for e in listed] == [
            ("Unread", False)
        ]

    async def test_the_deletion_is_recorded_for_syncing_clients(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A client that has the collection has to be told it went."""
        library_id = await personal_library(ada)
        key = await admin.create_api_key(session, username="ada", name="sync")
        made = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()
        before = int(
            (await ada.get("/users/1/collections", headers={"Zotero-API-Key": key.key})).headers[
                "Last-Modified-Version"
            ]
        )

        await ada.delete(
            f"/web/libraries/{library_id}/collections/{made['key']}", headers=csrf_headers(ada)
        )

        deleted = await ada.get(
            f"/users/1/deleted?since={before - 1}", headers={"Zotero-API-Key": key.key}
        )
        assert made["key"] in deleted.json()["collections"]

    async def test_an_unknown_collection_is_not_found(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.delete(
            f"/web/libraries/{library_id}/collections/AAAA2345", headers=csrf_headers(ada)
        )

        assert response.status_code == 404


class TestTheVersionCounter:
    async def test_one_request_is_one_new_version(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "Papers"},
            headers=csrf_headers(ada),
        )

        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert (await ada.get("/web/libraries")).json()[0]["version"] == before + 1

    async def test_the_collection_carries_the_new_library_version(
        self, ada: httpx.AsyncClient
    ) -> None:
        library_id = await personal_library(ada)

        body = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["version"] == (await ada.get("/web/libraries")).json()[0]["version"]

    async def test_a_refused_write_leaves_the_version_alone(self, ada: httpx.AsyncClient) -> None:
        """A client asking `?since=` must not be sent looking for nothing."""
        library_id = await personal_library(ada)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        await ada.post(
            f"/web/libraries/{library_id}/collections", json={"name": ""}, headers=csrf_headers(ada)
        )

        assert (await ada.get("/web/libraries")).json()[0]["version"] == before

    async def test_a_write_that_fails_after_the_bump_rolls_it_back(
        self, ada: httpx.AsyncClient
    ) -> None:
        """An unknown parent is found by the write, after the version moved."""
        library_id = await personal_library(ada)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        refused = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "Unread", "parentCollection": "AAAA2345"},
            headers=csrf_headers(ada),
        )

        assert refused.status_code == 404
        assert (await ada.get("/web/libraries")).json()[0]["version"] == before


class TestWhoMay:
    async def test_it_needs_a_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        library_id = await personal_library(client)
        headers = csrf_headers(client)
        client.cookies.delete("altero_session")

        response = await client.post(
            f"/web/libraries/{library_id}/collections", json={"name": "Papers"}, headers=headers
        )

        assert response.status_code == 401

    async def test_it_needs_the_csrf_token(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(
            f"/web/libraries/{library_id}/collections", json={"name": "Papers"}
        )

        assert response.status_code == 403
        assert await collection_names(ada, library_id) == []

    async def test_deleting_needs_the_csrf_token(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        made = (
            await ada.post(
                f"/web/libraries/{library_id}/collections",
                json={"name": "Papers"},
                headers=csrf_headers(ada),
            )
        ).json()

        response = await ada.delete(f"/web/libraries/{library_id}/collections/{made['key']}")

        assert response.status_code == 403
        assert await collection_names(ada, library_id) == ["Papers"]

    async def test_an_api_key_does_not_open_this_door(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The boundary in both directions: a key belongs to the v3 API."""
        library_id = await personal_library(ada)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        ada.cookies.clear()

        response = await ada.post(
            f"/web/libraries/{library_id}/collections",
            json={"name": "Papers"},
            headers={"Zotero-API-Key": key.key, "X-CSRF-Token": "anything"},
        )

        assert response.status_code == 401

    async def test_another_person_s_library_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None

        response = await ada.post(
            f"/web/libraries/{theirs.id}/collections",
            json={"name": "Papers"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403
        assert (
            await session.scalar(select(Collection).where(Collection.library_id == theirs.id))
            is None
        )

    async def test_a_missing_library_is_not_found(self, ada: httpx.AsyncClient) -> None:
        response = await ada.post(
            "/web/libraries/9999/collections", json={"name": "Papers"}, headers=csrf_headers(ada)
        )

        assert response.status_code == 404


class TestGroupPolicy:
    """A group decides who may change its library, and it decides it here too."""

    async def _group(self, session: AsyncSession, editing: str, role: str) -> Library:
        """A group somebody else owns, with Ada in it under ``role``."""
        grace = await admin.create_user(session, username="grace")
        return await factories.make_group(
            session,
            group_id=50,
            owner_id=grace.id,
            members={1: role},
            library_editing=editing,
        )

    async def test_a_member_of_an_open_group_may_make_one(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="members", role="member")

        response = await ada.post(
            f"/web/libraries/{library.id}/collections",
            json={"name": "Shared"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 201

    async def test_a_member_of_an_admins_only_group_may_not(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="admins", role="member")

        response = await ada.post(
            f"/web/libraries/{library.id}/collections",
            json={"name": "Shared"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403

    async def test_an_administrator_of_that_group_may(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="admins", role="admin")

        response = await ada.post(
            f"/web/libraries/{library.id}/collections",
            json={"name": "Shared"},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 201

    async def test_a_member_may_remove_one(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="members", role="member")
        made = (
            await ada.post(
                f"/web/libraries/{library.id}/collections",
                json={"name": "Shared"},
                headers=csrf_headers(ada),
            )
        ).json()

        response = await ada.delete(
            f"/web/libraries/{library.id}/collections/{made['key']}", headers=csrf_headers(ada)
        )

        assert response.status_code == 204

    async def test_a_member_of_an_admins_only_group_may_not_remove_one(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library = await self._group(session, editing="admins", role="member")
        collection = await factories.make_collection(session, library=library, name="Shared")

        response = await ada.delete(
            f"/web/libraries/{library.id}/collections/{collection.key}", headers=csrf_headers(ada)
        )

        assert response.status_code == 403
        assert await collection_names(ada, library.id) == ["Shared"]

    async def test_a_stranger_to_a_public_group_may_read_but_not_write(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        library = await factories.make_group(session, group_id=51, owner_id=grace.id, public=True)

        assert (await ada.get(f"/web/libraries/{library.id}/collections")).status_code == 200
        refused = await ada.post(
            f"/web/libraries/{library.id}/collections",
            json={"name": "Shared"},
            headers=csrf_headers(ada),
        )
        assert refused.status_code == 403


class TestTheLibraryList:
    """The interface offers the controls the server says are allowed."""

    async def test_a_personal_library_is_writable(self, ada: httpx.AsyncClient) -> None:
        assert (await ada.get("/web/libraries")).json()[0]["writable"] is True

    async def test_a_group_that_reserves_editing_is_not(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        library = await factories.make_group(
            session,
            group_id=50,
            owner_id=grace.id,
            members={1: "member"},
            library_editing="admins",
        )

        listed = (await ada.get("/web/libraries")).json()

        assert next(entry for entry in listed if entry["id"] == library.id)["writable"] is False
