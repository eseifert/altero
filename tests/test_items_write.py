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


class TestThePatchLeavesTheTwoFlagsAlone:
    """``deleted`` and ``inPublications`` under a partial write.

    ``Zotero_Items::updateFromJSON`` sets each only when the object mentions it
    or the write replaces -- ``if (isset($json->deleted) || !$partialUpdate)``,
    and the same line again for ``inPublications``. Collections and searches
    already followed that rule here; items did not, so any patch that did not
    restate them cleared both. Filing an item from the browser untrashed it,
    and publishing one that was in the trash brought it back out.
    """

    async def test_a_patch_that_says_nothing_leaves_it_in_the_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10, deleted=True)

        await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 10},
        )

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["deleted"] == 1

    async def test_a_patch_that_says_nothing_leaves_it_published(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10, in_publications=True)

        await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 10},
        )

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["inPublications"] is True

    async def test_a_patch_that_says_so_still_takes_it_out_of_the_trash(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """The client writes the flag out when it goes, rather than dropping it."""
        await make_item(session, library, key="AAAA2345", version=10, deleted=True)

        await client.patch(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "deleted": False, "version": 10},
        )

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert "deleted" not in body["data"]

    async def test_a_replacing_put_still_clears_what_it_leaves_out(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session, library, key="AAAA2345", version=10, deleted=True, in_publications=True
        )

        await client.put(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "title": "New", "version": 10},
        )

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert "deleted" not in body["data"]
        assert "inPublications" not in body["data"]


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

    async def test_deleting_a_parent_deletes_its_children(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # A note whose parent is gone has nothing to attach to, and leaving it
        # behind would point at a row that no longer exists.
        parent = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)

        await client.delete(
            "/users/1/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "10"}
        )

        assert (await client.get("/users/1/items", headers=AUTH)).json() == []

    async def test_a_deleted_child_is_reported_in_the_delete_log(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_item(session, library, key="AAAA2345")
        await make_item(session, library, key="BBBB2345", item_type="note", parent=parent)

        await client.delete(
            "/users/1/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "10"}
        )

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()
        assert sorted(body["items"]) == ["AAAA2345", "BBBB2345"]

    async def test_a_tag_left_with_no_items_is_removed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        from sqlalchemy import func, select

        from altero.models import Tag

        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        await client.delete(
            "/users/1/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "10"}
        )

        # The tag is already invisible over the API, which joins through items,
        # but the row would otherwise accumulate.
        remaining = await session.scalar(select(func.count()).select_from(Tag))
        assert remaining == 0

    async def test_a_tag_still_used_elsewhere_is_kept(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "fiction")
        await tag_item(session, library, two, "fiction")

        await client.delete(
            "/users/1/items/AAAA2345", headers=AUTH | {"If-Unmodified-Since-Version": "10"}
        )

        assert [t["tag"] for t in (await client.get("/users/1/tags", headers=AUTH)).json()] == [
            "fiction"
        ]

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


class TestUnlistedFields:
    """Attachments, notes and annotations carry data the schema does not list.

    Their field sets were taken from live responses; the published schema gives
    `attachment` only title, accessDate and url, and `note` and `annotation`
    nothing at all.
    """

    async def test_the_servers_own_attachment_template_round_trips(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # Whatever /items/new offers must be acceptable back.
        for mode in ("imported_file", "imported_url", "linked_file", "linked_url"):
            template = (await client.get(f"/items/new?itemType=attachment&linkMode={mode}")).json()

            response = await client.post("/users/1/items", headers=JSON, json=[template])

            assert response.json()["failed"] == {}, mode

    async def test_attachment_storage_fields_are_stored(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "attachment",
                        "linkMode": "imported_url",
                        "title": "Snapshot",
                        "url": "https://example.org/",
                        "contentType": "text/html",
                        "charset": "utf-8",
                        "filename": "page.html",
                        "md5": "0" * 32,
                        "mtime": "1700000000000",
                    }
                ],
            )
        ).json()

        assert body["failed"] == {}
        data = body["successful"]["0"]["data"]
        assert data["linkMode"] == "imported_url"
        assert data["contentType"] == "text/html"
        assert data["filename"] == "page.html"

    async def test_a_linked_file_keeps_its_path(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "attachment",
                        "linkMode": "linked_file",
                        "title": "Local",
                        "path": "attachments:paper.pdf",
                    }
                ],
            )
        ).json()

        assert body["successful"]["0"]["data"]["path"] == "attachments:paper.pdf"

    async def test_an_annotation_keeps_its_fields(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        parent = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[{"itemType": "attachment", "linkMode": "imported_file"}],
            )
        ).json()["successful"]["0"]["key"]

        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "annotation",
                        "parentItem": parent,
                        "annotationType": "highlight",
                        "annotationText": "a passage",
                        "annotationColor": "#ffd400",
                        "annotationSortIndex": "00001|000000|00000",
                    }
                ],
            )
        ).json()

        assert body["failed"] == {}
        data = body["successful"]["0"]["data"]
        assert data["annotationType"] == "highlight"
        assert data["annotationText"] == "a passage"

    async def test_a_storage_field_is_still_rejected_for_a_book(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[{"itemType": "book", "linkMode": "imported_file"}],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400


class TestClientTimestamps:
    async def test_supplied_timestamps_round_trip(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # A client uploading an existing library must not have its history
        # rewritten to the moment of upload.
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "book",
                        "title": "Old",
                        "dateAdded": "2019-01-01T10:00:00Z",
                        "dateModified": "2019-06-02T11:30:00Z",
                    }
                ],
            )
        ).json()

        data = body["successful"]["0"]["data"]
        assert data["dateAdded"] == "2019-01-01T10:00:00Z"
        assert data["dateModified"] == "2019-06-02T11:30:00Z"

    async def test_missing_timestamps_default_to_now(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post("/users/1/items", headers=JSON, json=[{"itemType": "book"}])
        ).json()

        data = body["successful"]["0"]["data"]
        assert data["dateAdded"].startswith("20")
        assert data["dateAdded"].endswith("Z")

    async def test_a_malformed_timestamp_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[{"itemType": "book", "dateAdded": "not a date"}],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_date_added_survives_an_update(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        created = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "book",
                        "title": "T",
                        "dateAdded": "2019-01-01T10:00:00Z",
                    }
                ],
            )
        ).json()["successful"]["0"]
        key, version = created["key"], created["version"]

        await client.patch(
            f"/users/1/items/{key}",
            headers=JSON,
            json={"itemType": "book", "title": "T2", "version": version},
        )

        body = (await client.get(f"/users/1/items/{key}", headers=AUTH)).json()
        assert body["data"]["dateAdded"] == "2019-01-01T10:00:00Z"


class TestPartialUploads:
    """The client uploads only what changed.

    Having synced an item once, it keeps the server's version in a local cache
    and later uploads a diff against it — `{key, version, ...changed fields}`
    with no `itemType`. Upstream treats such an object as a partial update and
    takes the item type from the stored item; requiring `itemType` rejects it
    and the client stops with "Made no progress during upload".
    """

    async def test_a_partial_object_updates_the_stored_item(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10, fields={"title": "Kept"})

        response = await client.post(
            "/users/1/items",
            headers=JSON,
            json=[{"key": "AAAA2345", "version": 10, "accessDate": "2026-01-01T00:00:00Z"}],
        )

        assert response.status_code == 200
        assert response.json()["failed"] == {}
        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        assert data["itemType"] == "book"
        assert data["title"] == "Kept"
        assert data["accessDate"] == "2026-01-01T00:00:00Z"

    async def test_the_exact_upload_the_client_sent(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Copied from a real sync: opening a snapshot updates lastRead only.
        await make_item(session, library, key="IJ7GDYP9", version=12, item_type="attachment")

        response = await client.post(
            "/users/1/items",
            headers=JSON,
            json=[
                {
                    "key": "IJ7GDYP9",
                    "version": 12,
                    "lastRead": 1785524654,
                    "dateModified": "2026-07-31T18:48:01Z",
                }
            ],
        )

        assert response.json()["failed"] == {}
        data = (await client.get("/users/1/items/IJ7GDYP9", headers=AUTH)).json()["data"]
        assert data["lastRead"] == "1785524654"

    async def test_a_new_item_still_needs_an_item_type(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        # Only an existing key makes an object partial.
        body = (
            await client.post(
                "/users/1/items", headers=JSON, json=[{"key": "ZZZZ2345", "version": 0}]
            )
        ).json()

        assert body["failed"]["0"]["code"] == 400
        assert "itemType" in body["failed"]["0"]["message"]

    async def test_an_object_with_no_key_at_all_needs_an_item_type(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (await client.post("/users/1/items", headers=JSON, json=[{}])).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_a_partial_update_leaves_other_fields_alone(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(
            session,
            library,
            key="AAAA2345",
            version=10,
            fields={"title": "Moby-Dick", "publisher": "Harper"},
            creators=[("author", "Herman", "Melville")],
        )

        await client.post(
            "/users/1/items",
            headers=JSON,
            json=[{"key": "AAAA2345", "version": 10, "publisher": "Penguin"}],
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        assert data["title"] == "Moby-Dick"
        assert data["publisher"] == "Penguin"
        assert data["creators"][0]["lastName"] == "Melville"

    async def test_a_stale_version_in_a_partial_object_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345", version=10)

        body = (
            await client.post(
                "/users/1/items", headers=JSON, json=[{"key": "AAAA2345", "version": 3}]
            )
        ).json()

        assert body["failed"]["0"]["code"] == 412

    async def test_last_read_is_accepted_on_an_attachment(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/items",
                headers=JSON,
                json=[
                    {
                        "itemType": "attachment",
                        "linkMode": "imported_url",
                        "title": "Snapshot",
                        "lastRead": 1785524654,
                    }
                ],
            )
        ).json()

        assert body["failed"] == {}
        assert body["successful"]["0"]["data"]["lastRead"] == "1785524654"

    async def test_a_patch_that_changes_the_type_keeps_the_rest(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """The one patch that carries `itemType`, and the one that lost data.

        `DataObjectUtilities.patch` drops every property equal to the cached
        copy, so a type change uploads as `{key, version, itemType}` and
        nothing else. Read as a replacement that emptied the item: title,
        publisher, creators, tags and collection membership all went. Upstream
        passes `$partialUpdate = true` for every object in a POST batch, so it
        sets what is there and leaves out what is not.
        """
        item = await make_item(
            session,
            library,
            key="AAAA2345",
            version=10,
            fields={"title": "Moby-Dick", "publisher": "Harper"},
            creators=[("author", "Herman", "Melville")],
        )
        await tag_item(session, library, item, "fiction")
        await make_collection(session, library, key="CCCC2345", name="Whales", items=[item])

        response = await client.post(
            "/users/1/items",
            headers=JSON,
            json=[{"key": "AAAA2345", "version": 10, "itemType": "journalArticle"}],
        )

        assert response.json()["failed"] == {}
        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        assert data["itemType"] == "journalArticle"
        assert data["title"] == "Moby-Dick"
        assert data["publisher"] == "Harper"
        assert data["creators"][0]["lastName"] == "Melville"
        assert data["tags"] == [{"tag": "fiction"}]
        assert data["collections"] == ["CCCC2345"]

    async def test_a_replacing_put_still_clears_what_it_leaves_out(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """`PUT` is the replacing write, and stays one."""
        await make_item(
            session,
            library,
            key="AAAA2345",
            version=10,
            fields={"title": "Moby-Dick", "publisher": "Harper"},
        )

        await client.put(
            "/users/1/items/AAAA2345",
            headers=JSON,
            json={"itemType": "book", "version": 10, "title": "Moby-Dick"},
        )

        data = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()["data"]
        assert data["title"] == "Moby-Dick"
        assert "publisher" not in data
