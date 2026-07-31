"""Writing items."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import make_api_key, make_collection, make_item, make_user, tag_item

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestCreate:
    async def test_an_item_is_created(self, client: httpx.AsyncClient, library: Library) -> None:
        response = await client.post(
            "/users/1/items", headers=JSON, json=[{"itemType": "book", "title": "Moby-Dick"}]
        )

        assert response.status_code == 200
        body = response.json()
        assert list(body) == ["successful", "success", "unchanged", "failed"]
        assert body["failed"] == {}
        created = body["successful"]["0"]
        assert created["data"]["title"] == "Moby-Dick"
        assert created["version"] == 11

    async def test_the_deprecated_success_map_is_also_emitted(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post("/users/1/items", headers=JSON, json=[{"itemType": "book"}])
        ).json()

        assert body["success"]["0"] == body["successful"]["0"]["key"]

    async def test_the_library_version_advances_once_per_request(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/items",
            headers=JSON,
            json=[{"itemType": "book"}, {"itemType": "thesis"}],
        )

        assert response.headers["Last-Modified-Version"] == "11"
        assert {obj["version"] for obj in response.json()["successful"].values()} == {11}

    async def test_a_single_object_may_be_sent_unwrapped(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post("/users/1/items", headers=JSON, json={"itemType": "book"})

        assert response.status_code == 200
        assert len(response.json()["successful"]) == 1

    async def test_a_client_supplied_key_is_kept(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[{"key": "AAAA2345", "itemType": "book"}],
            )
        ).json()

        assert body["successful"]["0"]["key"] == "AAAA2345"

    async def test_a_child_may_name_a_parent_from_the_same_request(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/items",
            headers=JSON,
            json=[
                {"key": "AAAA2345", "itemType": "book"},
                {"itemType": "note", "note": "A note", "parentItem": "AAAA2345"},
            ],
        )

        assert response.json()["failed"] == {}
        child = response.json()["successful"]["1"]
        assert child["data"]["parentItem"] == "AAAA2345"

    async def test_creators_tags_and_collections_are_stored(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="COLL2345")

        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "book",
                        "title": "Moby-Dick",
                        "creators": [
                            {
                                "creatorType": "author",
                                "firstName": "Herman",
                                "lastName": "Melville",
                            }
                        ],
                        "tags": [{"tag": "fiction"}, {"tag": "auto", "type": 1}],
                        "collections": ["COLL2345"],
                    }
                ],
            )
        ).json()

        data = body["successful"]["0"]["data"]
        assert data["creators"][0]["lastName"] == "Melville"
        assert {t["tag"] for t in data["tags"]} == {"fiction", "auto"}
        assert data["collections"] == ["COLL2345"]

    async def test_a_single_field_creator_is_stored(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "book",
                        "creators": [{"creatorType": "author", "name": "Some Institution"}],
                    }
                ],
            )
        ).json()

        assert body["successful"]["0"]["data"]["creators"] == [
            {"creatorType": "author", "name": "Some Institution"}
        ]

    async def test_writing_requires_write_permission(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await make_user(session, user_id=2, username="reader")
        await make_api_key(session, key="READONLY", user_id=2, library_write=False)

        response = await client.post(
            "/users/2/items",
            headers={"Zotero-API-Key": "READONLY"},
            json=[{"itemType": "book"}],
        )

        assert response.status_code == 403


class TestCreateFailures:
    async def test_an_unknown_item_type_fails_that_object_only(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/items",
            headers=JSON,
            json=[{"itemType": "book"}, {"itemType": "nosuch"}],
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body["successful"]) == {"0"}
        assert body["failed"]["1"]["code"] == 400
        assert "nosuch" in body["failed"]["1"]["message"]

    async def test_a_field_invalid_for_the_type_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[{"itemType": "book", "caseName": "Nope"}],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_an_unknown_field_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items", headers=JSON, json=[{"itemType": "book", "nope": "x"}]
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_an_invalid_creator_type_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "book",
                        "creators": [{"creatorType": "director", "lastName": "X"}],
                    }
                ],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_a_failed_object_does_not_advance_the_version(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post("/users/1/items", headers=JSON, json=[{"itemType": "nosuch"}])

        assert response.headers["Last-Modified-Version"] == "10"

    async def test_more_than_fifty_objects_are_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/items", headers=JSON, json=[{"itemType": "book"}] * 51
        )

        assert response.status_code == 413

    async def test_a_malformed_body_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post("/users/1/items", headers=JSON, json="nope")

        assert response.status_code == 400


class TestReplaceAndUpdate:
    async def test_put_replaces_the_whole_item(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="AAAA2345",
            version=10,
            fields={"title": "Old", "publisher": "Harper"},
        )

        response = await client.put(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 10},
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["title"] == "New"
        assert "publisher" not in body["data"]

    async def test_patch_leaves_untouched_properties_alone(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="AAAA2345",
            version=10,
            fields={"title": "Old", "publisher": "Harper"},
        )

        response = await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 10},
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["title"] == "New"
        assert body["data"]["publisher"] == "Harper"

    async def test_the_version_header_may_carry_the_precondition(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10)

        response = await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON | {"If-Unmodified-Since-Version": "10"},
            json={"itemType": "book", "title": "New"},
        )

        assert response.status_code == 204

    async def test_a_stale_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10)

        response = await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 3},
        )

        assert response.status_code == 412

    async def test_a_missing_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10)

        response = await client.patch(
            "/users/1/items/AAAA2345", headers=JSON, json={"itemType": "book"}
        )

        assert response.status_code == 428

    async def test_updating_advances_the_version(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10)

        response = await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 10},
        )

        assert response.headers["Last-Modified-Version"] == "11"

    async def test_an_item_can_be_moved_to_the_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10)

        await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "deleted": 1, "version": 10},
        )

        trash = (await client.get("/users/1/items/trash", headers=AUTH)).json()
        assert [i["key"] for i in trash] == ["AAAA2345"]


class TestDelete:
    async def test_an_item_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")

        response = await client.delete(
            "/users/1/items/AAAA2345",
            headers=AUTH | {"If-Unmodified-Since-Version": "10"},
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/items/AAAA2345", headers=AUTH)).status_code == 404

    async def test_deleting_without_a_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")

        response = await client.delete("/users/1/items/AAAA2345", headers=AUTH)

        assert response.status_code == 428
        assert response.text == "If-Unmodified-Since-Version not provided"

    async def test_deleting_with_a_stale_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")

        response = await client.delete(
            "/users/1/items/AAAA2345",
            headers=AUTH | {"If-Unmodified-Since-Version": "3"},
        )

        assert response.status_code == 412

    async def test_a_non_numeric_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")

        response = await client.delete(
            "/users/1/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "x"}
        )

        assert response.status_code == 400

    async def test_deleting_an_unknown_item_is_a_404(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.delete(
            "/users/1/items/ZZZZ2345", headers=AUTH | {"If-Unmodified-Since-Version": "10"}
        )

        assert response.status_code == 404

    async def test_several_items_are_deleted_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345")
        await make_item(session, library, key="CCCC2345")

        response = await client.delete(
            "/users/1/items?itemKey=AAAA2345,BBBB2345",
            headers=AUTH | {"If-Unmodified-Since-Version": "10"},
        )

        assert response.status_code == 204
        remaining = (await client.get("/users/1/items", headers=AUTH)).json()
        assert [i["key"] for i in remaining] == ["CCCC2345"]

    async def test_deleting_more_than_fifty_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        keys = ",".join(f"AAAA{n:04d}" for n in range(51))

        response = await client.delete(
            f"/users/1/items?itemKey={keys}",
            headers=AUTH | {"If-Unmodified-Since-Version": "10"},
        )

        assert response.status_code == 413

    async def test_deleting_an_item_removes_its_tag_links(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        await client.delete(
            "/users/1/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "10"}
        )

        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []


class TestWriteTokens:
    TOKEN = "a" * 32

    async def test_a_replayed_token_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        headers = JSON | {"Zotero-Write-Token": self.TOKEN}

        first = await client.post("/users/1/items", headers=headers, json=[{"itemType": "book"}])
        second = await client.post("/users/1/items", headers=headers, json=[{"itemType": "book"}])

        assert first.status_code == 200
        assert second.status_code == 412

    async def test_a_different_token_is_accepted(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        await client.post(
            "/users/1/items",
            headers=JSON | {"Zotero-Write-Token": self.TOKEN},
            json=[{"itemType": "book"}],
        )
        second = await client.post(
            "/users/1/items",
            headers=JSON | {"Zotero-Write-Token": "b" * 32},
            json=[{"itemType": "book"}],
        )

        assert second.status_code == 200

    async def test_a_malformed_token_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/items",
            headers=JSON | {"Zotero-Write-Token": "short"},
            json=[{"itemType": "book"}],
        )

        assert response.status_code == 400
