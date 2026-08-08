"""Reading a library through the web interface's own endpoints."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import admin
from tests import factories
from tests.test_web_routes import csrf_headers, register


class TestLibraries:
    async def test_the_personal_library_is_listed(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.get("/web/libraries")

        assert response.status_code == 200
        assert [library["type"] for library in response.json()] == ["user"]

    async def test_it_needs_a_session(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/libraries")).status_code == 401

    async def test_another_user_s_library_is_not_listed(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        await admin.create_user(session, username="grace")

        libraries = (await client.get("/web/libraries")).json()

        assert all(library["ownerId"] == 1 for library in libraries)


class TestItems:
    async def test_an_empty_library_lists_nothing_and_says_so(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

        response = await client.get(f"/web/libraries/{library_id}/items")

        assert response.status_code == 200
        assert response.json() == {"total": 0, "libraryVersion": 0, "items": []}

    async def test_items_come_back_in_the_v3_shape(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Same serialiser as the sync API, so there is one idea of an item."""
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="seed")
        await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key.key},
            json=[{"itemType": "book", "title": "Structure and Interpretation"}],
        )
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

        body = (await client.get(f"/web/libraries/{library_id}/items")).json()

        assert body["total"] == 1
        assert body["items"][0]["data"]["title"] == "Structure and Interpretation"
        assert body["items"][0]["data"]["itemType"] == "book"
        assert "key" in body["items"][0]

    async def test_another_user_s_library_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await admin.create_user(session, username="grace")
        from sqlalchemy import select

        from altero.models import Library, LibraryType

        other = await session.scalar(
            select(Library).where(Library.type == LibraryType.USER, Library.owner_id == grace.id)
        )
        assert other is not None

        response = await client.get(f"/web/libraries/{other.id}/items")

        assert response.status_code == 403

    async def test_a_missing_library_is_404(self, client: httpx.AsyncClient) -> None:
        await register(client)

        assert (await client.get("/web/libraries/9999/items")).status_code == 404

    async def test_an_absurd_limit_is_refused_rather_than_served(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

        response = await client.get(f"/web/libraries/{library_id}/items?limit=10000")

        assert response.status_code == 400

    async def test_signing_out_ends_access_to_the_library(self, client: httpx.AsyncClient) -> None:
        await register(client)
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        assert (await client.get("/web/libraries")).status_code == 401


class TestBrowsing:
    """The reads the interface needs beyond a flat list of items."""

    async def _seed(self, client: httpx.AsyncClient, session: AsyncSession) -> tuple[int, str]:
        """Register, then fill a library through the v3 API. Returns the library and key."""
        await register(client)
        key = await admin.create_api_key(session, username="ada", name="seed")
        library_id = (await client.get("/web/libraries")).json()[0]["id"]
        return library_id, key.key

    async def test_collections_come_back_as_a_whole_tree(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        auth = {"Zotero-API-Key": key}
        created = (
            await client.post("/users/1/collections", headers=auth, json=[{"name": "Papers"}])
        ).json()["successful"]["0"]
        await client.post(
            "/users/1/collections",
            headers=auth,
            json=[{"name": "Drafts", "parentCollection": created["key"]}],
        )

        body = (await client.get(f"/web/libraries/{library_id}/collections")).json()

        assert body["total"] == 2
        names = {entry["data"]["name"]: entry for entry in body["collections"]}
        assert names["Papers"]["meta"]["numCollections"] == 1
        assert names["Drafts"]["data"]["parentCollection"] == created["key"]

    async def test_items_can_be_narrowed_to_a_collection(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        auth = {"Zotero-API-Key": key}
        collection = (
            await client.post("/users/1/collections", headers=auth, json=[{"name": "Papers"}])
        ).json()["successful"]["0"]
        await client.post(
            "/users/1/items",
            headers=auth,
            json=[
                {"itemType": "book", "title": "In it", "collections": [collection["key"]]},
                {"itemType": "book", "title": "Not in it"},
            ],
        )

        body = (
            await client.get(f"/web/libraries/{library_id}/items?collection={collection['key']}")
        ).json()

        assert [entry["data"]["title"] for entry in body["items"]] == ["In it"]

    async def test_the_trash_is_its_own_scope(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        auth = {"Zotero-API-Key": key}
        await client.post(
            "/users/1/items",
            headers=auth,
            json=[
                {"itemType": "book", "title": "Discarded", "deleted": 1},
                {"itemType": "book", "title": "Kept"},
            ],
        )

        listed = (await client.get(f"/web/libraries/{library_id}/items")).json()
        trashed = (await client.get(f"/web/libraries/{library_id}/items?scope=trash")).json()

        assert [entry["data"]["title"] for entry in listed["items"]] == ["Kept"]
        assert [entry["data"]["title"] for entry in trashed["items"]] == ["Discarded"]

    async def test_my_publications_is_its_own_scope(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The row Zotero's own sidebar has, which the browser now offers too."""
        library_id, key = await self._seed(client, session)
        await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key},
            json=[
                {"itemType": "book", "title": "Published", "inPublications": True},
                {"itemType": "book", "title": "Private"},
            ],
        )

        published = (
            await client.get(f"/web/libraries/{library_id}/items?scope=publications")
        ).json()

        assert [entry["data"]["title"] for entry in published["items"]] == ["Published"]

    async def test_a_group_has_no_publications(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Publishing is something an account does with its own library. The
        sidebar does not draw the row for a group, and the endpoint refuses it
        rather than answering with an empty list that means something else."""
        await register(client)
        group = await factories.make_group(session, group_id=50, owner_id=1, members={})

        response = await client.get(f"/web/libraries/{group.id}/items?scope=publications")

        assert response.status_code == 400

    async def test_a_search_matches_more_than_the_title(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key},
            json=[
                {"itemType": "book", "title": "Whales", "publisher": "Nantucket Press"},
                {"itemType": "book", "title": "Squid"},
            ],
        )

        body = (await client.get(f"/web/libraries/{library_id}/items?q=Nantucket")).json()

        assert [entry["data"]["title"] for entry in body["items"]] == ["Whales"]

    async def test_items_can_be_filtered_by_tag(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key},
            json=[
                {"itemType": "book", "title": "Tagged", "tags": [{"tag": "toread"}]},
                {"itemType": "book", "title": "Untagged"},
            ],
        )

        body = (await client.get(f"/web/libraries/{library_id}/items?tag=toread")).json()

        assert [entry["data"]["title"] for entry in body["items"]] == ["Tagged"]

    async def test_tags_are_listed_with_their_counts(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key},
            json=[
                {"itemType": "book", "title": "One", "tags": [{"tag": "toread"}]},
                {"itemType": "book", "title": "Two", "tags": [{"tag": "toread"}]},
            ],
        )

        body = (await client.get(f"/web/libraries/{library_id}/tags")).json()

        assert body["tags"] == [{"tag": "toread", "type": 0, "numItems": 2}]

    async def test_one_item_is_readable_on_its_own(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        created = (
            await client.post(
                "/users/1/items",
                headers={"Zotero-API-Key": key},
                json=[{"itemType": "book", "title": "Alone"}],
            )
        ).json()["successful"]["0"]

        body = (await client.get(f"/web/libraries/{library_id}/items/{created['key']}")).json()

        assert body["data"]["title"] == "Alone"

    async def test_child_notes_and_attachments_are_listed(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        auth = {"Zotero-API-Key": key}
        parent = (
            await client.post(
                "/users/1/items", headers=auth, json=[{"itemType": "book", "title": "Parent"}]
            )
        ).json()["successful"]["0"]
        await client.post(
            "/users/1/items",
            headers=auth,
            json=[{"itemType": "note", "note": "<p>A thought</p>", "parentItem": parent["key"]}],
        )

        body = (
            await client.get(f"/web/libraries/{library_id}/items/{parent['key']}/children")
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["data"]["note"] == "<p>A thought</p>"

    async def test_an_unknown_sort_field_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The parameter reaches a SQL ORDER BY, so it is checked against the
        same list the v3 API accepts rather than passed through."""
        library_id, _ = await self._seed(client, session)

        response = await client.get(f"/web/libraries/{library_id}/items?sort=nonsense")

        assert response.status_code == 400

    async def test_reading_a_file_needs_the_session(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        library_id, key = await self._seed(client, session)
        created = (
            await client.post(
                "/users/1/items",
                headers={"Zotero-API-Key": key},
                json=[{"itemType": "attachment", "linkMode": "imported_file", "title": "PDF"}],
            )
        ).json()["successful"]["0"]
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        response = await client.get(f"/web/libraries/{library_id}/items/{created['key']}/file")

        assert response.status_code == 401


class TestFiles:
    """Attachment bytes reach the browser without an API key."""

    async def test_a_stored_file_is_served_to_the_session(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        from tests.test_files import CONTENT, authorization

        await register(client)
        key = (await admin.create_api_key(session, username="ada", name="seed")).key
        auth = {"Zotero-API-Key": key}
        library_id = (await client.get("/web/libraries")).json()[0]["id"]

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

        response = await client.get(f"/web/libraries/{library_id}/items/{created['key']}/file")

        assert response.status_code == 200
        assert response.content == CONTENT
        assert response.headers["content-type"].startswith("text/plain")
