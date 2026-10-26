"""Changing items from the browser: filing, trashing, deleting and copying.

The writes themselves are `services/itemwrites`, tested against the v3
endpoints in ``test_items_write.py``. What is checked here is what only this
door has: a cookie instead of a key, a CSRF token, who may write to which
library, one new version per request, and the rules this door adds — that a
permanent deletion happens only out of the trash, that a copy into another
library is a copy and never a move, and that a selection of rows is one errand
rather than one errand per row.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import GroupActivity, Item, Library, MemberPermission, User
from altero.services import admin, groups
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


def only(response: httpx.Response) -> dict[str, Any]:
    """The one item out of an answer that always names a selection.

    Filing, trashing and copying answer with a list because that is what they
    take. Most of what is checked here is about one item, and this asserts that
    one is all that came back on the way to reading it.
    """
    body = response.json()
    assert len(body["items"]) == 1
    return dict(body["items"][0])


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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert only(response)["data"]["collections"] == [papers]
        assert await listed(ada, library_id, collection=papers) == ["Structure and Interpretation"]

    async def test_filing_it_again_somewhere_else_keeps_the_first(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Dragging onto a collection adds; it does not move. Zotero's rule."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        books = await make_collection(ada, library_id, "Books")
        item = await seed_item(ada, session, collections=[papers])

        body = only(
            await ada.patch(
                f"/web/libraries/{library_id}/items",
                json={"items": [item], "addCollections": [books]},
                headers=csrf_headers(ada),
            )
        )

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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "addCollections": [books], "removeCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert only(response)["data"]["collections"] == [books]
        assert int(response.headers["Last-Modified-Version"]) == before + 1

    async def test_it_is_taken_out_of_the_only_collection_it_was_in(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The case a partial write cannot express: an empty array reads as
        "not mentioned", so this has to be its own thing."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = only(
            await ada.patch(
                f"/web/libraries/{library_id}/items",
                json={"items": [item], "removeCollections": [papers]},
                headers=csrf_headers(ada),
            )
        )

        assert body["data"]["collections"] == []
        assert await listed(ada, library_id, collection=papers) == []
        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_filing_it_where_it_already_is_changes_nothing_about_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = only(
            await ada.patch(
                f"/web/libraries/{library_id}/items",
                json={"items": [item], "addCollections": [papers]},
                headers=csrf_headers(ada),
            )
        )

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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert await listed(ada, library_id, scope="trash") == ["Structure and Interpretation"]

    async def test_a_request_that_asks_for_nothing_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Naming items is not an errand. A request the server can satisfy by
        doing nothing would still take a library version if it were allowed."""
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item]},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400
        assert (await ada.get("/web/libraries")).json()[0]["version"] == before

    async def test_an_unknown_collection_is_not_found(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "addCollections": ["BBBB2345"]},
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": False},
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

        body = only(
            await ada.patch(
                f"/web/libraries/{library_id}/items",
                json={"items": [item], "deleted": True},
                headers=csrf_headers(ada),
            )
        )

        assert body["data"]["collections"] == [papers]

    async def test_a_syncing_client_hears_about_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="sync")

        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
            headers=csrf_headers(ada),
        )

        response = await ada.delete(
            f"/web/libraries/{library_id}/items?itemKey={item}", headers=csrf_headers(ada)
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
            f"/web/libraries/{library_id}/items?itemKey={item}", headers=csrf_headers(ada)
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.delete(
            f"/web/libraries/{library_id}/items?itemKey={item}", headers=csrf_headers(ada)
        )

        deleted = await ada.get(
            f"/users/1/deleted?since={before}", headers={"Zotero-API-Key": key.key}
        )
        assert item in deleted.json()["items"]

    async def test_an_unknown_item_is_not_found(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.delete(
            f"/web/libraries/{library_id}/items?itemKey=AAAA2345", headers=csrf_headers(ada)
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
                f"/web/libraries/{library_id}/items",
                json={"items": [item], "deleted": True},
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
            f"/web/libraries/{library_id}/items",
            json={"items": [thrown], "deleted": True},
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
                f"/web/libraries/{library_id}/items",
                json={"items": [item], "deleted": True},
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
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
            f"/web/libraries/{library_id}/items/copy",
            json={"items": [item], "library": group.id},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 201
        assert only(response)["data"]["title"] == "Structure and Interpretation"
        assert await listed(ada, group.id) == ["Structure and Interpretation"]

    async def test_the_original_stays_where_it_was(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A copy and never a move: nothing leaves a library by being dragged."""
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)

        await ada.post(
            f"/web/libraries/{library_id}/items/copy",
            json={"items": [item], "library": group.id},
            headers=csrf_headers(ada),
        )

        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_the_copy_is_its_own_item(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await self._group(session)
        item = await seed_item(ada, session)

        body = only(
            await ada.post(
                f"/web/libraries/{library_id}/items/copy",
                json={"items": [item], "library": group.id},
                headers=csrf_headers(ada),
            )
        )

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

        body = only(
            await ada.post(
                f"/web/libraries/{library_id}/items/copy",
                json={"items": [item], "library": group.id, "collection": target.key},
                headers=csrf_headers(ada),
            )
        )

        assert body["data"]["collections"] == [target.key]

    async def test_the_collections_it_was_in_do_not_come_with_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """They are collections in the library it left, and mean nothing here."""
        library_id = await personal_library(ada)
        group = await self._group(session)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session, collections=[papers])

        body = only(
            await ada.post(
                f"/web/libraries/{library_id}/items/copy",
                json={"items": [item], "library": group.id},
                headers=csrf_headers(ada),
            )
        )

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

        copied = only(
            await ada.post(
                f"/web/libraries/{library_id}/items/copy",
                json={"items": [item], "library": group.id},
                headers=csrf_headers(ada),
            )
        )

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

        body = only(
            await ada.post(
                f"/web/libraries/{library_id}/items/copy",
                json={"items": [item], "library": group.id},
                headers=csrf_headers(ada),
            )
        )

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
            f"/web/libraries/{library_id}/items/copy",
            json={"items": [item], "library": library_id},
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
            f"/web/libraries/{library_id}/items/copy",
            json={"items": [item], "library": theirs.id},
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
            f"/web/libraries/{theirs.id}/items/copy",
            json={"items": [elsewhere.key], "library": group.id},
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
            f"/web/libraries/{library_id}/items/copy",
            json={"items": [item], "library": group.id},
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
            f"/web/libraries/{library_id}/items", json={"items": [item], "deleted": True}
        )

        assert response.status_code == 403
        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_deleting_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        item = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
            headers=csrf_headers(ada),
        )

        response = await ada.delete(f"/web/libraries/{library_id}/items?itemKey={item}")

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
            f"/web/libraries/{library_id}/items/copy", json={"items": [item], "library": group.id}
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
            f"/web/libraries/{library_id}/items",
            json={"items": [item], "deleted": True},
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
            f"/web/libraries/{theirs.id}/items",
            json={"items": [item.key], "deleted": True},
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
            f"/web/libraries/{group.id}/items",
            json={"items": [item.key], "deleted": True},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403


class TestEditingAnItem:
    """One item edited: its fields, creators, tags, relations and note.

    A partial write through the same `save_item` a syncing client's goes
    through, holding the version it replaces, because text typed over somebody
    else's change is a lost write. What a property is cleared by is the v3 rule:
    sent empty clears it, left out leaves it alone.
    """

    async def key_of(self, ada: httpx.AsyncClient, session: AsyncSession) -> tuple[int, str]:
        library_id = await personal_library(ada)
        return library_id, await seed_item(ada, session)

    async def version_of(self, ada: httpx.AsyncClient, library_id: int, key: str) -> int:
        payload = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()
        return int(payload["version"])

    async def edit(
        self, ada: httpx.AsyncClient, library_id: int, item_key: str, **changes: object
    ) -> httpx.Response:
        """Write ``changes`` over the version the page was last shown."""
        version = await self.version_of(ada, library_id, item_key)
        return await ada.patch(
            f"/web/libraries/{library_id}/items/{item_key}",
            json={"version": version, **changes},
            headers=csrf_headers(ada),
        )

    async def test_a_field_is_written(self, ada: httpx.AsyncClient, session: AsyncSession) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(ada, library_id, key, fields={"title": "SICP"})

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "SICP"
        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data["title"] == "SICP"

    async def test_the_rights_field_is_written(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The licence of a published work, which this route began by writing."""
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(ada, library_id, key, fields={"rights": "CC BY 4.0"})

        assert response.json()["data"]["rights"] == "CC BY 4.0"

    async def test_several_fields_are_one_new_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)
        before = await self.version_of(ada, library_id, key)

        response = await self.edit(
            ada,
            library_id,
            key,
            fields={"title": "SICP", "publisher": "MIT Press", "date": "1985"},
            creators=[{"creatorType": "author", "firstName": "Harold", "lastName": "Abelson"}],
            tags=[{"tag": "lisp"}],
        )

        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert response.json()["version"] == before + 1

    async def test_it_leaves_everything_else_alone(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A partial write: what is not mentioned is not touched."""
        library_id, key = await self.key_of(ada, session)
        papers = await make_collection(ada, library_id, "Papers")
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [key], "addCollections": [papers]},
            headers=csrf_headers(ada),
        )
        await self.edit(ada, library_id, key, tags=[{"tag": "lisp"}])

        await self.edit(ada, library_id, key, fields={"rights": "All rights reserved"})

        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data["title"] == "Structure and Interpretation"
        assert data["collections"] == [papers]
        assert data["tags"] == [{"tag": "lisp"}]

    async def test_an_emptied_field_is_cleared(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)
        await self.edit(ada, library_id, key, fields={"publisher": "MIT Press"})

        await self.edit(ada, library_id, key, fields={"publisher": ""})

        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data["publisher"] == ""

    async def test_creators_are_written_in_order(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)
        creators = [
            {"creatorType": "author", "firstName": "Harold", "lastName": "Abelson"},
            {"creatorType": "author", "firstName": "Gerald Jay", "lastName": "Sussman"},
        ]

        response = await self.edit(ada, library_id, key, creators=creators)

        assert response.json()["data"]["creators"] == creators
        assert response.json()["meta"]["creatorSummary"] == "Abelson and Sussman"

    async def test_the_sort_keys_follow_the_edit(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Derived on every write, so the list sorts by what it now shows."""
        library_id = await personal_library(ada)
        first = await seed_item(ada, session, title="Alpha", key_name="a")
        await seed_item(ada, session, title="Beta", key_name="b")

        await self.edit(ada, library_id, first, fields={"title": "Gamma"})

        assert await listed(ada, library_id, sort="title") == ["Beta", "Gamma"]

    async def test_empty_creators_clear_them_and_absent_ones_do_not(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)
        await self.edit(
            ada,
            library_id,
            key,
            creators=[{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}],
        )

        await self.edit(ada, library_id, key, fields={"title": "Kept"})
        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert len(data["creators"]) == 1

        await self.edit(ada, library_id, key, creators=[])
        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data.get("creators", []) == []

    async def test_a_creator_type_the_item_type_lacks_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(
            ada, library_id, key, creators=[{"creatorType": "director", "name": "Someone"}]
        )

        assert response.status_code == 400
        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data.get("creators", []) == []

    async def test_tags_are_written_and_cleared(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(
            ada, library_id, key, tags=[{"tag": "lisp"}, {"tag": "auto", "type": 1}]
        )
        assert sorted(tag["tag"] for tag in response.json()["data"]["tags"]) == ["auto", "lisp"]

        response = await self.edit(ada, library_id, key, tags=[])
        assert response.json()["data"]["tags"] == []

    async def test_relations_are_written(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)
        other = await seed_item(ada, session, title="Other", key_name="other")
        uri = f"http://zotero.org/users/1/items/{other}"

        response = await self.edit(ada, library_id, key, relations={"dc:relation": uri})

        assert response.json()["data"]["relations"] == {"dc:relation": uri}

    async def test_a_note_is_written(self, ada: httpx.AsyncClient, session: AsyncSession) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="note")
        created = await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "note", "parentItem": parent, "note": "<p>first</p>"}],
        )
        note = created.json()["successful"]["0"]["key"]

        response = await self.edit(ada, library_id, note, note="<p>second</p>")

        assert response.status_code == 200
        assert response.json()["data"]["note"] == "<p>second</p>"
        assert response.json()["data"]["parentItem"] == parent

    async def test_a_book_has_no_note_to_write(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(ada, library_id, key, note="<p>x</p>")

        assert response.status_code == 400
        assert "not a valid field" in response.json()["message"]

    async def test_a_type_without_the_field_is_refused_as_a_client_would_be(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """A note has no `rights`, and `save_item` is what says so."""
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)
        key = await admin.create_api_key(session, username="ada", name="note")
        created = await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "note", "parentItem": parent, "note": "<p>x</p>"}],
        )
        note = created.json()["successful"]["0"]["key"]

        response = await self.edit(ada, library_id, note, fields={"rights": "CC0"})

        assert response.status_code == 400
        assert "not a valid field" in response.json()["message"]

    async def test_an_unknown_field_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(ada, library_id, key, fields={"colour": "red"})

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "name",
        [
            "key",
            "version",
            "parentItem",
            "collections",
            "deleted",
            "inPublications",
            "dateAdded",
            "dateModified",
        ],
    )
    async def test_a_property_this_route_does_not_write_is_refused_by_name(
        self, ada: httpx.AsyncClient, session: AsyncSession, name: str
    ) -> None:
        """Each of these is read-only or has a route of its own.

        Named in ``fields`` it would have reached `save_item` as the property
        itself, and a browser could have rewritten when an item was added.
        """
        library_id, key = await self.key_of(ada, session)
        before = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()

        for changes in ({"fields": {name: "x"}}, {name: "x"} if name != "version" else None):
            if changes is None:
                continue
            response = await self.edit(ada, library_id, key, **changes)

            assert response.status_code == 400, changes
            assert response.json()["message"] == f"'{name}' cannot be changed here"

        after = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()
        assert after == before

    async def test_a_property_nobody_knows_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(ada, library_id, key, colour="red")

        assert response.status_code == 400
        assert response.json()["message"] == "Unknown property 'colour'"

    async def test_a_stale_version_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Text is not an errand the server can work out for itself.

        Filing and trashing are add-and-remove against what is stored, so a
        stale page cannot express a wrong one. Typing over a field somebody
        else changed while the page sat open is a lost write.
        """
        library_id, key = await self.key_of(ada, session)
        stale = await self.version_of(ada, library_id, key)
        await ada.patch(
            f"/web/libraries/{library_id}/items/{key}",
            json={"fields": {"title": "First"}, "version": stale},
            headers=csrf_headers(ada),
        )

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{key}",
            json={"fields": {"title": "Second"}, "version": stale},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 412
        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data["title"] == "First"

    async def test_an_edit_without_a_version_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{key}",
            json={"fields": {"title": "Untitled"}},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 428

    async def test_an_edit_that_writes_nothing_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)

        response = await self.edit(ada, library_id, key, fields={})

        assert response.status_code == 400

    async def test_an_edit_that_changes_nothing_takes_no_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Leaving a field as it was is not a change for every client to fetch.

        Stored with a `dateModified` in the past, so that the edit, which sends
        none, cannot pass by happening within the same second as the seed.
        """
        library_id = await personal_library(ada)
        api_key = await admin.create_api_key(session, username="ada", name="seed")
        created = await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": api_key.key},
            json=[
                {
                    "itemType": "book",
                    "title": "Structure and Interpretation",
                    "dateModified": "2020-01-01T00:00:00Z",
                }
            ],
        )
        key = created.json()["successful"]["0"]["key"]
        # Seeded last, so the item's version is the library's too.
        before = await self.version_of(ada, library_id, key)

        response = await self.edit(
            ada, library_id, key, fields={"title": "Structure and Interpretation"}
        )

        assert response.status_code == 200
        assert response.json()["version"] == before
        assert response.headers["Last-Modified-Version"] == str(before)

    async def test_an_item_in_the_trash_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The desktop's trash is read-only too: restoring is the way back."""
        library_id, key = await self.key_of(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [key], "deleted": True},
            headers=csrf_headers(ada),
        )

        response = await self.edit(ada, library_id, key, fields={"title": "Changed"})

        assert response.status_code == 400
        assert "trash" in response.json()["message"]

    async def test_it_needs_the_csrf_token(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self.key_of(ada, session)
        version = await self.version_of(ada, library_id, key)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{key}",
            json={"fields": {"title": "Changed"}, "version": version},
        )

        assert response.status_code == 403

    async def test_a_read_only_library_refuses_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        grace = await admin.create_user(session, username="grace")
        theirs = await session.scalar(select(Library).where(Library.owner_id == grace.id))
        assert theirs is not None
        item = await factories.make_item(session, theirs, fields={"title": "Theirs"})
        await session.commit()

        response = await ada.patch(
            f"/web/libraries/{theirs.id}/items/{item.key}",
            json={"fields": {"rights": "CC0"}, "version": item.version},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403

    async def test_a_member_held_to_reading_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = await self.group_with_ada(session, MemberPermission.READ)
        item = await factories.make_item(session, group, fields={"title": "Theirs"})
        await session.commit()

        response = await ada.patch(
            f"/web/libraries/{group.id}/items/{item.key}",
            json={"fields": {"title": "Mine"}, "version": item.version},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403

    async def test_a_member_held_to_their_own_cannot_edit_somebody_elses(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = await self.group_with_ada(session, MemberPermission.OWN)
        item = await factories.make_item(session, group, fields={"title": "Theirs"})
        await session.commit()

        response = await ada.patch(
            f"/web/libraries/{group.id}/items/{item.key}",
            json={"fields": {"title": "Mine"}, "version": item.version},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 403
        await session.refresh(item)
        assert item.version == 1

    async def test_a_member_held_to_adding_may_edit_anybodys(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """`add` withholds removing, not changing: the v3 rule."""
        group = await self.group_with_ada(session, MemberPermission.ADD)
        item = await factories.make_item(session, group, fields={"title": "Theirs"})
        await session.commit()

        response = await ada.patch(
            f"/web/libraries/{group.id}/items/{item.key}",
            json={"fields": {"title": "Ours"}, "version": item.version},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "Ours"

    async def group_with_ada(self, session: AsyncSession, permission: str) -> Library:
        """A group of Grace's in which Ada is a member held to ``permission``."""
        grace = await admin.create_user(session, username="grace")
        group = await factories.make_group(
            session, group_id=52, owner_id=grace.id, members={1: "member"}
        )
        ada = await session.get(User, 1)
        assert ada is not None
        await groups.set_permission(session, group, ada, permission)
        await session.commit()
        return group


class TestChangingTheType:
    """The item pane's type menu: the desktop's mapping, and a warning first.

    A change that would throw fields away answers 409 naming them, and goes
    through only when the browser sends the same names back in `discard` --
    which a page showing an older warning cannot do for fields it never saw.
    """

    async def book(self, ada: httpx.AsyncClient, session: AsyncSession, **fields: str) -> str:
        api_key = await admin.create_api_key(session, username="ada", name="seed")
        created = await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": api_key.key},
            json=[
                {
                    "itemType": "book",
                    "title": "SICP",
                    "creators": [
                        {"creatorType": "author", "firstName": "Harold", "lastName": "Abelson"}
                    ],
                    **fields,
                }
            ],
        )
        return str(created.json()["successful"]["0"]["key"])

    async def retype(
        self, ada: httpx.AsyncClient, key: str, item_type: str, **extra: object
    ) -> httpx.Response:
        library_id = await personal_library(ada)
        version = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["version"]
        return await ada.patch(
            f"/web/libraries/{library_id}/items/{key}",
            json={"version": version, "itemType": item_type, **extra},
            headers=csrf_headers(ada),
        )

    async def test_a_change_that_loses_nothing_goes_through(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session, publisher="MIT Press")

        response = await self.retype(ada, key, "report")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["itemType"] == "report"
        assert data["institution"] == "MIT Press"
        assert "publisher" not in data

    async def test_a_change_that_loses_fields_names_them_first(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session, edition="2", numPages="657")

        response = await self.retype(ada, key, "film")

        assert response.status_code == 409
        assert response.json()["data"] == {"fields": ["edition", "numPages"]}
        library_id = await personal_library(ada)
        data = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["data"]
        assert data["itemType"] == "book"
        assert data["edition"] == "2"

    async def test_naming_them_back_goes_through(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session, edition="2", numPages="657")

        response = await self.retype(ada, key, "film", discard=["numPages", "edition"])

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["itemType"] == "film"
        assert not {"edition", "numPages"} & set(data)
        # The desktop's mapping: a book's author is a film's director.
        assert data["creators"][0]["creatorType"] == "director"

    async def test_a_warning_about_other_fields_does_not_count(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Somebody added a page count since the page showed its warning."""
        key = await self.book(ada, session, edition="2", numPages="657")

        response = await self.retype(ada, key, "film", discard=["edition"])

        assert response.status_code == 409
        assert response.json()["data"] == {"fields": ["edition", "numPages"]}

    async def test_it_is_one_new_version_that_a_desktop_hears_about(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session)
        api_key = await admin.create_api_key(session, username="ada", name="desktop")
        since = (
            await ada.get("/users/1/items?format=versions", headers={"Zotero-API-Key": api_key.key})
        ).headers["Last-Modified-Version"]

        response = await self.retype(ada, key, "report")

        assert int(response.headers["Last-Modified-Version"]) == int(since) + 1
        changed = await ada.get(
            f"/users/1/items?since={since}&format=versions",
            headers={"Zotero-API-Key": api_key.key},
        )
        assert changed.json() == {key: int(since) + 1}

    async def test_the_same_type_changes_nothing(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session)
        library_id = await personal_library(ada)
        before = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["version"]

        response = await self.retype(ada, key, "book")

        assert response.status_code == 200
        assert response.json()["version"] == before

    async def test_a_note_keeps_its_type(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        made = await ada.post(
            f"/web/libraries/{library_id}/items",
            json={"itemType": "note"},
            headers=csrf_headers(ada),
        )

        response = await self.retype(ada, made.json()["key"], "book")

        assert response.status_code == 400

    async def test_a_type_change_comes_on_its_own(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session)

        response = await self.retype(ada, key, "report", fields={"title": "Other"})

        assert response.status_code == 400

    async def test_the_type_is_not_a_field(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        key = await self.book(ada, session)
        library_id = await personal_library(ada)
        version = (await ada.get(f"/web/libraries/{library_id}/items/{key}")).json()["version"]

        response = await ada.patch(
            f"/web/libraries/{library_id}/items/{key}",
            json={"version": version, "fields": {"itemType": "report"}},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400


class TestCreatingAnItem:
    """A new item from the type picker: the v3 template, written by `save_item`.

    What the browser sends is the type and where the item goes. The rest is the
    template `/items/new` serves, so a book made here is the book a v3 client
    creating from that template would have made, down to its empty fields.
    """

    async def create(
        self, ada: httpx.AsyncClient, library_id: int, **body: object
    ) -> httpx.Response:
        return await ada.post(
            f"/web/libraries/{library_id}/items", json=body, headers=csrf_headers(ada)
        )

    async def test_a_book_is_created(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await self.create(ada, library_id, itemType="book")

        assert response.status_code == 201
        item = response.json()
        assert item["data"]["itemType"] == "book"
        assert item["data"]["title"] == ""
        assert await listed(ada, library_id) == [""]

    async def test_it_is_the_template_without_its_nameless_creator(
        self, ada: httpx.AsyncClient
    ) -> None:
        library_id = await personal_library(ada)
        template = (await ada.get("/items/new?itemType=book")).json()

        data = (await self.create(ada, library_id, itemType="book")).json()["data"]

        expected = {name for name in template if name != "creators"}
        assert expected <= set(data)
        assert "creators" not in data

    async def test_it_is_one_new_version(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        before = await self.create(ada, library_id, itemType="book")

        response = await self.create(ada, library_id, itemType="journalArticle")

        version = int(before.headers["Last-Modified-Version"])
        assert int(response.headers["Last-Modified-Version"]) == version + 1
        assert response.json()["version"] == version + 1

    async def test_it_is_filed_where_it_was_made(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")

        response = await self.create(ada, library_id, itemType="book", collections=[papers])

        assert response.json()["data"]["collections"] == [papers]
        assert await listed(ada, library_id, collection=papers) == [""]

    async def test_an_unknown_collection_is_not_found(self, ada: httpx.AsyncClient) -> None:
        """As filing answers it, and nothing is made."""
        library_id = await personal_library(ada)

        response = await self.create(ada, library_id, itemType="book", collections=["ZZZZ2345"])

        assert response.status_code == 404
        assert response.json()["message"] == "Collection ZZZZ2345 not found"
        assert await listed(ada, library_id) == []
        assert await listed(ada, library_id) == []

    async def test_a_child_note_is_created_under_its_parent(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)

        response = await self.create(ada, library_id, itemType="note", parentItem=parent)

        assert response.status_code == 201
        assert response.json()["data"]["parentItem"] == parent
        assert response.json()["data"]["note"] == ""
        children = (await ada.get(f"/web/libraries/{library_id}/items/{parent}/children")).json()
        assert [child["key"] for child in children["items"]] == [response.json()["key"]]

    async def test_a_standalone_note_is_created(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await self.create(ada, library_id, itemType="note")

        assert response.status_code == 201
        assert "parentItem" not in response.json()["data"]

    async def test_a_book_cannot_have_a_parent(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)

        response = await self.create(ada, library_id, itemType="book", parentItem=parent)

        assert response.status_code == 400
        assert await listed(ada, library_id) == ["Structure and Interpretation"]

    async def test_a_note_cannot_go_under_a_note(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)
        note = (await self.create(ada, library_id, itemType="note", parentItem=parent)).json()

        response = await self.create(ada, library_id, itemType="note", parentItem=note["key"])

        assert response.status_code == 400

    async def test_a_note_cannot_go_under_an_item_in_the_trash(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        parent = await seed_item(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [parent], "deleted": True},
            headers=csrf_headers(ada),
        )

        response = await self.create(ada, library_id, itemType="note", parentItem=parent)

        assert response.status_code == 400
        assert "trash" in response.json()["message"]

    async def test_an_unknown_parent_is_not_found(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await self.create(ada, library_id, itemType="note", parentItem="ZZZZ2345")

        assert response.status_code == 404

    async def test_an_unknown_type_is_refused(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await self.create(ada, library_id, itemType="nosuch")

        assert response.status_code == 400

    @pytest.mark.parametrize("item_type", ["attachment", "annotation"])
    async def test_a_type_with_its_own_way_in_is_refused(
        self, ada: httpx.AsyncClient, item_type: str
    ) -> None:
        """Attachments come with a file or a link, annotations from a reader."""
        library_id = await personal_library(ada)

        response = await self.create(ada, library_id, itemType=item_type)

        assert response.status_code == 400
        assert await listed(ada, library_id) == []

    async def test_it_needs_the_csrf_token(self, ada: httpx.AsyncClient) -> None:
        library_id = await personal_library(ada)

        response = await ada.post(f"/web/libraries/{library_id}/items", json={"itemType": "book"})

        assert response.status_code == 403
        assert await listed(ada, library_id) == []

    async def test_a_read_only_library_refuses_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = await TestEditingAnItem().group_with_ada(session, MemberPermission.READ)

        response = await self.create(ada, group.id, itemType="book")

        assert response.status_code == 403

    async def test_a_member_held_to_adding_may_create(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        group = await TestEditingAnItem().group_with_ada(session, MemberPermission.ADD)

        response = await self.create(ada, group.id, itemType="book")

        assert response.status_code == 201
        assert response.json()["meta"]["createdByUser"]["id"] == 1

    async def test_a_syncing_client_hears_about_it(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        api_key = await admin.create_api_key(session, username="ada", name="desktop")
        since = (
            await ada.get("/users/1/items?format=versions", headers={"Zotero-API-Key": api_key.key})
        ).headers["Last-Modified-Version"]

        made = (await self.create(ada, library_id, itemType="book")).json()

        changed = await ada.get(
            f"/users/1/items?since={since}&format=versions",
            headers={"Zotero-API-Key": api_key.key},
        )
        assert changed.json() == {made["key"]: made["version"]}


class TestASelection:
    """Several rows picked out and dragged somewhere: one errand, one version.

    The reader who selected twenty rows and dropped them on a collection did one
    thing. What is checked here is that the server treats it as one — a single
    new library version, a single entry in a group's activity, and all of it or
    none of it.
    """

    async def _group(self, session: AsyncSession) -> Library:
        return await factories.make_group(
            session, group_id=50, owner_id=1, members={}, name="Whale Watchers"
        )

    async def _three(self, ada: httpx.AsyncClient, session: AsyncSession) -> list[str]:
        return [
            await seed_item(ada, session, title=name.capitalize(), key_name=name)
            for name in ("one", "two", "three")
        ]

    async def test_a_selection_is_filed_in_one_request(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        items = await self._three(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": items, "addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 200
        assert [entry["key"] for entry in response.json()["items"]] == items
        assert sorted(await listed(ada, library_id, collection=papers)) == ["One", "Three", "Two"]

    async def test_however_many_rows_it_is_one_new_version(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The whole reason the endpoint takes a list. Three requests would be
        three versions, and every syncing client would fetch three times."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        items = await self._three(ada, session)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": items, "addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert {entry["version"] for entry in response.json()["items"]} == {before + 1}

    async def test_each_row_keeps_the_collections_only_it_was_in(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Filing is worked out per item against what is stored, so a selection
        does not flatten three different filings into one."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        books = await make_collection(ada, library_id, "Books")
        loose = await seed_item(ada, session, title="Loose", key_name="loose")
        filed = await seed_item(ada, session, title="Filed", collections=[books], key_name="filed")

        body = (
            await ada.patch(
                f"/web/libraries/{library_id}/items",
                json={"items": [loose, filed], "addCollections": [papers]},
                headers=csrf_headers(ada),
            )
        ).json()

        collections = {
            entry["key"]: sorted(entry["data"]["collections"]) for entry in body["items"]
        }
        assert collections[loose] == [papers]
        assert collections[filed] == sorted([books, papers])

    async def test_a_selection_moves_out_of_one_collection_and_into_another(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Shift-dragging a selection: the removal and the addition together."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        books = await make_collection(ada, library_id, "Books")
        first = await seed_item(ada, session, title="One", collections=[papers], key_name="one")
        second = await seed_item(ada, session, title="Two", collections=[papers], key_name="two")

        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={
                "items": [first, second],
                "addCollections": [books],
                "removeCollections": [papers],
            },
            headers=csrf_headers(ada),
        )

        assert await listed(ada, library_id, collection=papers) == []
        assert sorted(await listed(ada, library_id, collection=books)) == ["One", "Two"]

    async def test_a_selection_goes_to_the_trash_together(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        items = await self._three(ada, session)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": items, "deleted": True},
            headers=csrf_headers(ada),
        )

        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert await listed(ada, library_id) == []
        assert sorted(await listed(ada, library_id, scope="trash")) == ["One", "Three", "Two"]

    async def test_a_selection_comes_back_out_together(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        items = await self._three(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": items, "deleted": True},
            headers=csrf_headers(ada),
        )

        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": items, "deleted": False},
            headers=csrf_headers(ada),
        )

        assert sorted(await listed(ada, library_id)) == ["One", "Three", "Two"]
        assert await listed(ada, library_id, scope="trash") == []

    async def test_a_selection_is_deleted_for_good_in_one_request(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        items = await self._three(ada, session)
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": items, "deleted": True},
            headers=csrf_headers(ada),
        )
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.delete(
            f"/web/libraries/{library_id}/items?itemKey={','.join(items)}",
            headers=csrf_headers(ada),
        )

        assert response.status_code == 204
        assert int(response.headers["Last-Modified-Version"]) == before + 1
        assert await listed(ada, library_id, scope="trash") == []

    async def test_one_row_outside_the_trash_refuses_the_whole_selection(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The trash is the undo, and it is the undo for every row named. A
        request that deleted the trashed ones and refused the rest would leave a
        reader with no way to tell which of the two had happened."""
        library_id = await personal_library(ada)
        trashed = await seed_item(ada, session, title="Trashed", key_name="trashed")
        kept = await seed_item(ada, session, title="Kept", key_name="kept")
        await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [trashed], "deleted": True},
            headers=csrf_headers(ada),
        )
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.delete(
            f"/web/libraries/{library_id}/items?itemKey={trashed},{kept}",
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400
        assert await listed(ada, library_id, scope="trash") == ["Trashed"]
        assert (await ada.get("/web/libraries")).json()[0]["version"] == before

    async def test_a_key_naming_nothing_writes_none_of_the_others(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Everything is resolved before anything is written, so a selection is
        filed or it is not — never half filed with no way to say which half."""
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session)
        before = (await ada.get("/web/libraries")).json()[0]["version"]

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [item, "AAAA2345"], "addCollections": [papers]},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 404
        assert await listed(ada, library_id, collection=papers) == []
        assert (await ada.get("/web/libraries")).json()[0]["version"] == before

    async def test_the_same_row_named_twice_is_written_once(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, "Papers")
        item = await seed_item(ada, session)

        body = (
            await ada.patch(
                f"/web/libraries/{library_id}/items",
                json={"items": [item, item], "addCollections": [papers]},
                headers=csrf_headers(ada),
            )
        ).json()

        assert [entry["key"] for entry in body["items"]] == [item]

    async def test_an_empty_selection_is_refused(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        await seed_item(ada, session)

        response = await ada.patch(
            f"/web/libraries/{library_id}/items",
            json={"items": [], "deleted": True},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 400

    async def test_a_selection_is_copied_into_a_group_in_one_request(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id = await personal_library(ada)
        group = await self._group(session)
        items = await self._three(ada, session)
        before = {
            entry["id"]: entry["version"] for entry in (await ada.get("/web/libraries")).json()
        }

        response = await ada.post(
            f"/web/libraries/{library_id}/items/copy",
            json={"items": items, "library": group.id},
            headers=csrf_headers(ada),
        )

        assert response.status_code == 201
        assert len(response.json()["items"]) == 3
        assert int(response.headers["Last-Modified-Version"]) == before[group.id] + 1
        assert sorted(await listed(ada, group.id)) == ["One", "Three", "Two"]
        assert sorted(await listed(ada, library_id)) == ["One", "Three", "Two"]

    async def test_a_group_hears_about_it_as_one_change(
        self, ada: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """One row in the log saying three items changed, rather than three rows
        saying one each: what the members are told is what happened."""
        grace = await admin.create_user(session, username="grace")
        group = await factories.make_group(
            session, group_id=52, owner_id=1, members={grace.id: "member"}
        )
        items = [
            (await factories.make_item(session, group, fields={"title": name})).key
            for name in ("One", "Two", "Three")
        ]
        await session.commit()

        await ada.patch(
            f"/web/libraries/{group.id}/items",
            json={"items": items, "deleted": True},
            headers=csrf_headers(ada),
        )

        activity = (await session.scalars(select(GroupActivity))).all()
        assert [entry.count for entry in activity] == [3]


class TestTheCostOfASelection:
    """A selection costs the same few statements whether it is three rows or fifteen."""

    async def _errand(
        self, app: Any, ada: httpx.AsyncClient, session: AsyncSession, count: int, errand: dict
    ) -> int:
        from tests.test_query_counts import capture_sql

        library_id = await personal_library(ada)
        papers = await make_collection(ada, library_id, f"Papers {count}")
        key = await admin.create_api_key(session, username="ada", name=f"seed {count}")
        created = await ada.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "book", "title": f"Book {n}"} for n in range(count)],
        )
        items = [entry["key"] for entry in created.json()["successful"].values()]
        body = {"items": items, **errand}
        if "addCollections" in body:
            body["addCollections"] = [papers]

        with capture_sql(app) as statements:
            response = await ada.patch(
                f"/web/libraries/{library_id}/items", json=body, headers=csrf_headers(ada)
            )

        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == count
        return len(statements)

    @pytest.mark.parametrize(
        "errand", [{"addCollections": []}, {"deleted": True}], ids=["filing", "trashing"]
    )
    async def test_more_rows_cost_no_more_statements(
        self,
        app: Any,
        ada: httpx.AsyncClient,
        session: AsyncSession,
        errand: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Timestamps are kept to the second, and SQLAlchemy batches rows into
        # one UPDATE only when they change the same columns. Fifteen items
        # created across a second boundary would leave some already stamped
        # with the second they are trashed in, and those would make a second
        # UPDATE -- a count about the clock rather than about the selection.
        from datetime import datetime as real

        from altero.services import itemwrites

        class Frozen(real):
            @classmethod
            def now(cls, tz: Any = None) -> Frozen:
                return cls(2026, 1, 1, 12, 0, 0, tzinfo=tz)

        monkeypatch.setattr(itemwrites, "datetime", Frozen)

        few = await self._errand(app, ada, session, 3, errand)
        many = await self._errand(app, ada, session, 15, errand)

        assert many == few
