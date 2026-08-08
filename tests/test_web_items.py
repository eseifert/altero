"""Changing items from the browser: filing, trashing, deleting and copying.

The writes themselves are `services/itemwrites`, tested against the v3
endpoints in ``test_items_write.py``. What is checked here is what only this
door has: a cookie instead of a key, a CSRF token, who may write to which
library, one new version per request, and the rules this door adds — that a
permanent deletion happens only out of the trash, and that a copy into another
library is a copy and never a move.
"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library
from altero.services import admin
from tests import factories
from tests.test_web_routes import csrf_headers, register


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
    assert response.status_code == 201
    return str(response.json()["key"])


async def seed_item(
    client: httpx.AsyncClient,
    session: AsyncSession,
    *,
    title: str = "Structure and Interpretation",
    collections: list[str] | None = None,
    key_name: str = "seed",
) -> str:
    """One book, put there the way a syncing client would put it there."""
    key = await admin.create_api_key(session, username="ada", name=key_name)
    payload: dict[str, object] = {"itemType": "book", "title": title}
    if collections:
        payload["collections"] = collections
    response = await client.post(
        "/users/1/items", headers={"Zotero-API-Key": key.key}, json=[payload]
    )
    assert response.status_code == 200
    return str(response.json()["successful"]["0"]["key"])


async def listed(client: httpx.AsyncClient, library_id: int, **query: str) -> list[str]:
    """The titles the interface would draw, in the scope asked for."""
    request = "&".join(f"{name}={value}" for name, value in query.items())
    payload = (await client.get(f"/web/libraries/{library_id}/items?{request}")).json()
    return [entry["data"].get("title", "") for entry in payload["items"]]


class TestFiling:
    async def test_an_item_is_put_into_a_collection(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert response.json()["data"]["collections"] == [papers]
        assert await listed(ada, library_id, collection=papers) == ["Structure and Interpretation"]

    async def test_filing_it_again_somewhere_else_keeps_the_first(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Dragging onto a collection adds; it does not move. Zotero's rule."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        books = await make_collection(ada, library_id, "Books")
        item = await seed_item(ada, session, collections=[papers])

        body = (
            await ada.patch(
                f"/web/libraries/{library_id}/items/{item}",
                json={"addCollections": [books]},
                headers=csrf_headers(ada),
            )
        ).json()

        assert sorted(body["data"]["collections"]) == sorted([papers, books])

    async def test_a_move_is_one_request_and_one_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Shift-dragging takes it out of where it was and puts it where it went."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        books = await make_collection(ada, library_id, "Books")
        item = await seed_item(ada, session, collections=[papers])
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"addCollections": [books], "removeCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert response.json()["data"]["collections"] == [books]
        assert int(response.headers["Last-Modified-Version"]) == before + 1

    async def test_it_is_taken_out_of_the_only_collection_it_was_in(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The case a partial write cannot express: an empty array reads as
        "not mentioned", so this has to be its own thing."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = (
            await ada.patch(
                f"/web/libraries/{library_id}/items/{item}",
                json={"removeCollections": [papers]},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["data"]["collections"] == []
        assert await listed(ada, library_id, collection=papers) == []
        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_filing_it_where_it_already_is_changes_nothing_about_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = (
            await ada.patch(
                f"/web/libraries/{library_id}/items/{item}",
                json={"addCollections": [papers]},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["data"]["collections"] == [papers]

    async def test_filing_does_not_untrash(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A partial write clears `deleted` unless it is restated, and filing
        something is not restoring it."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert await listed(ada, library_id, scope="trash") == ["Structure and Interpretation"]

    async def test_an_unknown_collection_is_not_found(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"addCollections": ["BBBB2345"]},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 404


class TestTheTrash:
    async def test_an_item_is_moved_to_the_trash(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert await listed(ada, library_id) == []
        assert await listed(ada, library_id, scope="trash") == ["Structure and Interpretation"]

    async def test_it_comes_back_out_again(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Which is the whole reason the browser trashes rather than deletes."""
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": False},
            headers=csrf_headers(ada),
        )

        assert await listed(ada, library_id) == ["Structure and Interpretation"]
        assert await listed(ada, library_id, scope="trash") == []

    async def test_trashing_keeps_it_filed_where_it_was(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """So that restoring puts it back where it came from."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = (
            await ada.patch(
                f"/web/libraries/{library_id}/items/{item}",
                json={"deleted": True},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["data"]["collections"] == [papers]

    async def test_a_syncing_client_hears_about_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="sync")

        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        trashed = await ada.get("/users/1/items/trash", headers={"Zotero-API-Key": key.key})
        assert [entry["key"] for entry in trashed.json()] == [item]


class TestDeletingForGood:
    async def test_an_item_in_the_trash_is_deleted(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        response = await ada.delete(
            f"/web/libraries/{library_id}/items/{item}", headers=csrf_headers(ada)
        )

        assert response.status_code == 204
        assert await listed(ada, library_id, scope="trash") == []
        assert await session.scalar(select(Item).where(Item.key == item)) is None

    async def test_an_item_still_in_the_library_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The browser has no undo, so the trash is the undo. Something that
        has never been trashed cannot be deleted by one request."""
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)

        response = await ada.delete(
            f"/web/libraries/{library_id}/items/{item}", headers=csrf_headers(ada)
        )

        assert response.status_code == 400
        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_the_deletion_is_recorded_for_syncing_clients(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="sync")
        before = int(
            (await ada.get("/users/1/items", headers={"Zotero-API-Key": key.key})).headers[
                "Last-Modified-Version"
            ]
        )
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.delete(f"/web/libraries/{library_id}/items/{item}", headers=csrf_headers(ada))

        deleted = await ada.get(
            f"/users/1/deleted?since={before}", headers={"Zotero-API-Key": key.key}
        )
        assert item in deleted.json()["items"]

    async def test_an_unknown_item_is_not_found(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.delete(
            f"/web/libraries/{library_id}/items/AAAA2345", headers=csrf_headers(ada)
        )

        assert response.status_code == 404


class TestEmptyingTheTrash:
    async def test_everything_in_the_trash_goes(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        first = await seed_item(ada, session, title="One", key_name="one")
        second = await seed_item(ada, session, title="Two", key_name="two")
        for item in (first, second):
            await ada.patch(
                f"/web/libraries/{library_id}/items/{item}",
                json={"deleted": True},
                headers=csrf_headers(ada),
            )

        response = await ada.delete(f"/web/libraries/{library_id}/trash", headers=csrf_headers(ada))

        assert response.status_code == 200
        assert response.json() == {"deleted": 2}
        assert await listed(ada, library_id, scope="trash") == []

    async def test_what_is_not_in_the_trash_stays(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        kept = await seed_item(ada, session, title="Kept", key_name="kept")
        thrown = await seed_item(ada, session, title="Thrown", key_name="thrown")
        await ada.patch(
            f"/web/libraries/{library_id}/items/{thrown}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.delete(f"/web/libraries/{library_id}/trash", headers=csrf_headers(ada))

        assert await listed(ada, library_id) == ["Kept"]
        assert await session.scalar(select(Item).where(Item.key == kept)) is not None

    async def test_an_empty_trash_is_not_a_new_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Nothing was written, so nothing changed. A library that announced a
        new version because somebody looked at an empty trash would send every
        syncing client to fetch nothing."""
        library_id = await personal_library(ada)
        await seed_item(ada, session)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.delete(f"/web/libraries/{library_id}/trash", headers=csrf_headers(ada))

        assert response.json() == {"deleted": 0}
        assert (await ada.get("/web/libraries")).json()[0]["version"] == before

    async def test_however_many_items_it_is_one_new_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        for name in ("one", "two", "three"):
            item = await seed_item(ada, session, title=name, key_name=name)
            await ada.patch(
                f"/web/libraries/{library_id}/items/{item}",
                json={"deleted": True},
                headers=csrf_headers(ada),
            )
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.delete(f"/web/libraries/{library_id}/trash", headers=csrf_headers(ada))

        assert int(response.headers["Last-Modified-Version"]) == before + 1

    async def test_the_deletions_are_recorded_for_syncing_clients(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="sync")
        before = int(
            (await ada.get("/users/1/items", headers={"Zotero-API-Key": key.key})).headers[
                "Last-Modified-Version"
            ]
        )
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.delete(f"/web/libraries/{library_id}/trash", headers=csrf_headers(ada))

        deleted = await ada.get(
            f"/users/1/deleted?since={before}", headers={"Zotero-API-Key": key.key}
        )
        assert item in deleted.json()["items"]

    async def test_it_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        response = await ada.delete(f"/web/libraries/{library_id}/trash")

        assert response.status_code == 403
        assert await listed(ada, library_id, scope="trash") == ["Structure and Interpretation"]

    async def test_a_library_this_account_cannot_write_to_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None
        item = await factories.make_item(
            session, theirs, fields={"title": "Not yours"}, deleted=True
        )

        response = await ada.delete(f"/web/libraries/{theirs.id}/trash", headers=csrf_headers(ada))

        assert response.status_code == 403
        assert await session.scalar(select(Item).where(Item.key == item.key)) is not None


class TestCopyingToAnotherLibrary:
    async def _group(self, session: AsyncSession) -> Library:
        """A group Ada may write to."""
        return await factories.make_group(
            session, group_id=50, owner_id=1, members={}, name="Whale Watchers"
        )

    async def test_an_item_is_copied_into_a_group(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)

        response = await ada.post(
            f"/web/libraries/{library_id}/items/{item}/copy",
            json={"library": group.id},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 201
        assert response.json()["data"]["title"] == "Structure and Interpretation"
        assert await listed(ada, group.id) == ["Structure and Interpretation"]

    async def test_the_original_stays_where_it_was(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A copy and never a move: nothing leaves a library by being dragged."""
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)

        await ada.post(
            f"/web/libraries/{library_id}/items/{item}/copy",
            json={"library": group.id},
            headers=csrf_headers(ada),
        )

        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_the_copy_is_its_own_item(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)

        body = (
            await ada.post(
                f"/web/libraries/{library_id}/items/{item}/copy",
                json={"library": group.id},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["key"] != item
        # The library block names a group by its Zotero group id, as the v3
        # API does, rather than by the row it happens to be stored in.
        assert body["library"]["id"] == group.owner_id

    async def test_it_lands_in_the_collection_it_was_dropped_on(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)
        target = await factories.make_collection(session, group, name="Sightings")

        body = (
            await ada.post(
                f"/web/libraries/{library_id}/items/{item}/copy",
                json={"library": group.id, "collection": target.key},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["data"]["collections"] == [target.key]

    async def test_the_collections_it_was_in_do_not_come_with_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """They are collections in the library it left, and mean nothing here."""
        library_id = await personal_library(ada)
        group = await self._group(session)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = (
            await ada.post(
                f"/web/libraries/{library_id}/items/{item}/copy",
                json={"library": group.id},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["data"]["collections"] == []

    async def test_its_notes_and_attachments_come_with_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A copy of a book without the note somebody wrote on it is not the
        copy they asked for."""
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="notes")
        await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "note", "note": "<p>Read chapter 3</p>", "parentItem": item}],
        )

        copied = (
            await ada.post(
                f"/web/libraries/{library_id}/items/{item}/copy",
                json={"library": group.id},
                headers=csrf_headers(ada),
            )
        ).json()

        children = await ada.get(f"/web/libraries/{group.id}/items/{copied['key']}/children")
        assert [entry["data"]["note"] for entry in children.json()["items"]] == [
            "<p>Read chapter 3</p>"
        ]

    async def test_the_tags_come_with_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await self._group(session)
        key = await admin.create_api_key(session, username="ada", name="tagged")
        made = await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "book", "title": "Tagged", "tags": [{"tag": "toread"}]}],
        )
        item = made.json()["successful"]["0"]["key"]

        body = (
            await ada.post(
                f"/web/libraries/{library_id}/items/{item}/copy",
                json={"library": group.id},
                headers=csrf_headers(ada),
            )
        ).json()

        assert body["data"]["tags"] == [{"tag": "toread"}]

    async def test_copying_into_the_same_library_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Two identical items in one library is nobody's intention, and the
        sidebar cannot express it: the row it was dragged from is the row it
        would be dropped on."""
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)

        response = await ada.post(
            f"/web/libraries/{library_id}/items/{item}/copy",
            json={"library": library_id},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400

    async def test_a_library_this_account_cannot_write_to_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None

        response = await ada.post(
            f"/web/libraries/{library_id}/items/{item}/copy",
            json={"library": theirs.id},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403
        assert await session.scalar(select(Item).where(Item.library_id == theirs.id)) is None

    async def test_a_library_this_account_cannot_read_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The other direction: copying *out* of somebody else's library."""
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None
        elsewhere = await factories.make_item(session, theirs, fields={"title": "Not yours"})
        group = await self._group(session)

        response = await ada.post(
            f"/web/libraries/{theirs.id}/items/{elsewhere.key}/copy",
            json={"library": group.id},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403

    async def test_one_request_is_one_new_version_of_the_target(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Only the library that gained something moves. The one the item came
        from did not change, and a version bump there would tell every client
        it had."""
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)
        before = {
            entry["id"]: entry["version"] for entry in (await ada.get("/web/libraries")).json()
        }

        response = await ada.post(
            f"/web/libraries/{library_id}/items/{item}/copy",
            json={"library": group.id},
            headers=csrf_headers(ada),
        )

        after = {
            entry["id"]: entry["version"] for entry in (await ada.get("/web/libraries")).json()
        }
        assert int(response.headers["Last-Modified-Version"]) == before[group.id] + 1
        assert after[group.id] == before[group.id] + 1
        assert after[library_id] == before[library_id]


class TestWhoMay:
    async def test_patching_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{item}", json={"deleted": True}
        )

        assert response.status_code == 403
        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_deleting_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        response = await ada.delete(f"/web/libraries/{library_id}/items/{item}")

        assert response.status_code == 403
        assert await listed(ada, library_id, scope="trash") == ["Structure and Interpretation"]

    async def test_copying_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await factories.make_group(
            session, group_id=50, owner_id=1, members={}, name="Whale Watchers"
        )
        item = await seed_item(ada, session)

        response = await ada.post(
            f"/web/libraries/{library_id}/items/{item}/copy", json={"library": group.id}
        )

        assert response.status_code == 403
        assert await listed(ada, group.id) == []

    async def test_an_api_key_does_not_open_this_door(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The boundary in both directions: a key belongs to the v3 API."""
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="laptop")
        ada.cookies.clear()

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{item}",
            json={"deleted": True},
            headers={"Zotero-API-Key": key.key, "X-CSRF-Token": "anything"},
        )

        assert response.status_code == 401

    async def test_another_person_s_item_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None
        item = await factories.make_item(session, theirs, fields={"title": "Not yours"})

        response = await ada.patch(
            f"/web/libraries/{theirs.id}/items/{item.key}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403

    async def test_a_group_that_reserves_editing_refuses_a_member(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        group = await factories.make_group(
            session,
            group_id=51,
            owner_id=grace.id,
            members={1: "member"},
            library_editing="admins",
        )
        item = await factories.make_item(session, group, fields={"title": "Theirs"})

        response = await ada.patch(
            f"/web/libraries/{group.id}/items/{item.key}",
            json={"deleted": True},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403
