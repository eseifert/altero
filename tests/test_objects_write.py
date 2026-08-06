"""Writing collections, saved searches and tags, and the delete log."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType
from altero.services.auth import get_library
from tests.factories import (
    make_api_key,
    make_collection,
    make_item,
    make_search,
    make_user,
    tag_item,
)

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"
AUTH = {"Zotero-API-Key": KEY}
JSON = AUTH | {"Content-Type": "application/json"}
VERSIONED = AUTH | {"If-Unmodified-Since-Version": "10"}


@pytest.fixture
async def library(session: AsyncSession) -> Library:
    await make_user(session, user_id=1)
    await make_api_key(session, key=KEY, user_id=1)
    library = await get_library(session, LibraryType.USER, 1)
    library.version = 10
    await session.commit()
    return library


class TestAPostedBatchIsPatches:
    """An object in a POST batch that names an existing one is a diff.

    `Zotero_DataObjects::updateMultipleFromJSON` passes `$partialUpdate = true`
    for every object in the batch, and validation is relaxed with
    `$partialUpdate && $exists`, so an object that names one already stored may
    leave out anything it is not changing.

    This is not a corner of the protocol. The desktop client uploads a *patch*
    whenever it has the previous version cached -- `syncEngine.js` reads
    `syncCache` and passes it as `patchBase` -- so a collection sent to the
    trash arrives as `{key, version, deleted}` and nothing else. Refusing that
    stops the upload, and the client answers "made no progress" and gives up on
    the whole library.
    """

    async def test_trashing_a_collection_needs_no_name(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", name="more", version=10)

        response = await client.post(
            "/users/1/collections",
            headers=JSON,
            json=[{"key": "AAAA2345", "version": 10, "deleted": True}],
        )

        assert response.json()["failed"] == {}
        body = (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).json()
        assert body["data"]["deleted"] == 1
        assert body["data"]["name"] == "more"

    async def test_trashing_a_search_needs_no_name(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(
            session,
            library,
            key="AAAA2345",
            name="Whales",
            version=10,
            conditions=[("title", "contains", "whale")],
        )

        response = await client.post(
            "/users/1/searches",
            headers=JSON,
            json=[{"key": "AAAA2345", "version": 10, "deleted": True}],
        )

        assert response.json()["failed"] == {}
        body = (await client.get("/users/1/searches/AAAA2345", headers=AUTH)).json()
        assert body["data"]["deleted"] == 1
        assert body["data"]["name"] == "Whales"
        assert body["data"]["conditions"][0]["value"] == "whale"

    async def test_a_patch_leaves_the_parent_where_it_was(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_collection(session, library, key="AAAA2345", name="Whales")
        await make_collection(session, library, key="BBBB2345", name="more", parent=parent)

        await client.post(
            "/users/1/collections",
            headers=JSON,
            json=[{"key": "BBBB2345", "version": 1, "deleted": True}],
        )

        body = (await client.get("/users/1/collections/BBBB2345", headers=AUTH)).json()
        assert body["data"]["parentCollection"] == "AAAA2345"

    async def test_a_new_collection_still_needs_a_name(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        """Only an object that exists may leave things out."""
        body = (
            await client.post("/users/1/collections", headers=JSON, json=[{"key": "AAAA2345"}])
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_a_new_search_still_needs_its_conditions(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post("/users/1/searches", headers=JSON, json=[{"name": "Whales"}])
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_a_patch_that_renames_leaves_the_rest_alone(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(
            session,
            library,
            key="AAAA2345",
            name="Whales",
            version=10,
            conditions=[("title", "contains", "whale")],
        )

        await client.post(
            "/users/1/searches",
            headers=JSON,
            json=[{"key": "AAAA2345", "version": 10, "name": "Cetaceans"}],
        )

        body = (await client.get("/users/1/searches/AAAA2345", headers=AUTH)).json()
        assert body["data"]["name"] == "Cetaceans"
        assert body["data"]["conditions"][0]["value"] == "whale"


class TestCollectionWrites:
    async def test_a_collection_is_created(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.post(
            "/users/1/collections", headers=JSON, json=[{"name": "Fiction"}]
        )

        assert response.status_code == 200
        created = response.json()["successful"]["0"]
        assert created["data"]["name"] == "Fiction"
        assert created["data"]["parentCollection"] is False
        assert created["version"] == 11

    async def test_a_nested_collection_is_created(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", name="Parent")

        body = (
            await client.post(
                "/users/1/collections",
                headers=JSON,
                json=[{"name": "Child", "parentCollection": "AAAA2345"}],
            )
        ).json()

        assert body["successful"]["0"]["data"]["parentCollection"] == "AAAA2345"

    async def test_a_collection_without_a_name_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (await client.post("/users/1/collections", headers=JSON, json=[{}])).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_an_unknown_parent_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post(
                "/users/1/collections",
                headers=JSON,
                json=[{"name": "Child", "parentCollection": "ZZZZ2345"}],
            )
        ).json()

        assert body["failed"]["0"]["code"] == 404

    async def test_a_collection_is_replaced(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", name="Old", version=10)

        response = await client.put(
            "/users/1/collections/AAAA2345",
            headers=JSON,
            json={"name": "New", "version": 10},
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).json()
        assert body["data"]["name"] == "New"

    async def test_replacing_with_a_stale_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345", version=10)

        response = await client.put(
            "/users/1/collections/AAAA2345", headers=JSON, json={"name": "New", "version": 2}
        )

        assert response.status_code == 412

    async def test_a_collection_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")

        response = await client.delete("/users/1/collections/AAAA2345", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).status_code == 404

    async def test_deleting_promotes_nested_collections(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        grandparent = await make_collection(session, library, key="AAAA2345")
        parent = await make_collection(session, library, key="BBBB2345", parent=grandparent)
        await make_collection(session, library, key="CCCC2345", parent=parent)

        await client.delete("/users/1/collections/BBBB2345", headers=VERSIONED)

        child = (await client.get("/users/1/collections/CCCC2345", headers=AUTH)).json()
        assert child["data"]["parentCollection"] == "AAAA2345"

    async def test_deleting_without_a_version_is_rejected(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")

        assert (
            await client.delete("/users/1/collections/AAAA2345", headers=AUTH)
        ).status_code == 428

    async def test_several_collections_are_deleted_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")
        await make_collection(session, library, key="BBBB2345")

        response = await client.delete(
            "/users/1/collections?collectionKey=AAAA2345,BBBB2345", headers=VERSIONED
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/collections", headers=AUTH)).json() == []


class TestSearchWrites:
    async def test_a_search_is_created(self, client: httpx.AsyncClient, library: Library) -> None:
        response = await client.post(
            "/users/1/searches",
            headers=JSON,
            json=[
                {
                    "name": "Whales",
                    "conditions": [
                        {"condition": "title", "operator": "contains", "value": "whale"}
                    ],
                }
            ],
        )

        assert response.status_code == 200
        created = response.json()["successful"]["0"]
        assert created["data"]["name"] == "Whales"
        assert created["data"]["conditions"][0]["value"] == "whale"

    async def test_a_search_without_conditions_is_rejected(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (
            await client.post("/users/1/searches", headers=JSON, json=[{"name": "Empty"}])
        ).json()

        assert body["failed"]["0"]["code"] == 400

    async def test_a_search_is_replaced(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(
            session,
            library,
            key="AAAA2345",
            name="Old",
            version=10,
            conditions=[("title", "contains", "whale")],
        )

        response = await client.put(
            "/users/1/searches/AAAA2345",
            headers=JSON,
            json={
                "name": "New",
                "version": 10,
                "conditions": [{"condition": "title", "operator": "contains", "value": "squid"}],
            },
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/searches/AAAA2345", headers=AUTH)).json()
        assert body["data"]["name"] == "New"
        assert body["data"]["conditions"][0]["value"] == "squid"

    async def test_patching_a_search_leaves_what_it_does_not_mention(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(
            session,
            library,
            key="AAAA2345",
            name="Old",
            version=10,
            conditions=[("title", "contains", "whale")],
        )

        response = await client.patch(
            "/users/1/searches/AAAA2345", headers=JSON, json={"name": "New", "version": 10}
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/searches/AAAA2345", headers=AUTH)).json()
        assert body["data"]["name"] == "New"
        assert body["data"]["conditions"][0]["value"] == "whale"

    async def test_replacing_a_search_needs_its_conditions(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """A `PUT` clears what it leaves out, and a saved search with no
        conditions is not a saved search."""
        await make_search(
            session, library, key="AAAA2345", version=10, conditions=[("title", "is", "x")]
        )

        response = await client.put(
            "/users/1/searches/AAAA2345", headers=JSON, json={"name": "New", "version": 10}
        )

        assert response.status_code == 400

    async def test_patching_a_collection_leaves_what_it_does_not_mention(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_collection(session, library, key="PPPP2345", name="Parent", version=10)
        await make_collection(
            session, library, key="AAAA2345", name="Old", version=10, parent=parent
        )

        response = await client.patch(
            "/users/1/collections/AAAA2345", headers=JSON, json={"name": "New", "version": 10}
        )

        assert response.status_code == 204
        body = (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).json()
        assert body["data"]["name"] == "New"
        assert body["data"]["parentCollection"] == "PPPP2345"

    async def test_replacing_a_collection_clears_its_parent(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        parent = await make_collection(session, library, key="PPPP2345", name="Parent", version=10)
        await make_collection(
            session, library, key="AAAA2345", name="Old", version=10, parent=parent
        )

        await client.put(
            "/users/1/collections/AAAA2345", headers=JSON, json={"name": "New", "version": 10}
        )

        body = (await client.get("/users/1/collections/AAAA2345", headers=AUTH)).json()
        assert body["data"]["parentCollection"] is False

    async def test_a_search_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="AAAA2345")

        response = await client.delete("/users/1/searches/AAAA2345", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/searches/AAAA2345", headers=AUTH)).status_code == 404

    async def test_several_searches_are_deleted_by_key(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="AAAA2345")
        await make_search(session, library, key="BBBB2345")

        response = await client.delete(
            "/users/1/searches?searchKey=AAAA2345,BBBB2345", headers=VERSIONED
        )

        assert response.status_code == 204
        assert (await client.get("/users/1/searches", headers=AUTH)).json() == []


class TestTagWrites:
    async def test_a_tag_is_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        response = await client.delete("/users/1/tags?tag=fiction", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []

    async def test_deleting_a_tag_leaves_the_item(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        await client.delete("/users/1/tags?tag=fiction", headers=VERSIONED)

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["tags"] == []

    async def test_several_tags_are_deleted_with_alternatives(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await tag_item(session, library, item, "classic")

        response = await client.delete("/users/1/tags?tag=fiction || classic", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []

    async def test_both_types_of_a_name_are_removed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "shared", tag_type=0)
        await tag_item(session, library, two, "shared", tag_type=1)

        await client.delete("/users/1/tags?tag=shared", headers=VERSIONED)

        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []

    async def test_deleting_without_a_tag_deletes_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The desktop client sends its tag names as `tags`, which its own
        # parameter filter then drops, so the request arrives bare. Upstream
        # answers 204 having done nothing, and the client accepts only 204 or
        # 412 here — a 400 aborts the sync.
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        response = await client.delete("/users/1/tags", headers=VERSIONED)

        assert response.status_code == 204
        assert [t["tag"] for t in (await client.get("/users/1/tags", headers=AUTH)).json()] == [
            "fiction"
        ]

    async def test_the_plural_parameter_is_also_accepted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # Should the client ever stop dropping it, `tags` means the same thing,
        # and its values are joined with a bare `||` rather than a spaced one.
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await tag_item(session, library, item, "classic")

        response = await client.delete("/users/1/tags?tags=fiction||classic", headers=VERSIONED)

        assert response.status_code == 204
        assert (await client.get("/users/1/tags", headers=AUTH)).json() == []


class TestRenamingATag:
    """`PATCH <prefix>/tags/<name>`, which upstream does not serve.

    The behaviour copied is the desktop client's `Zotero.Tags.rename`: both
    types of the name are renamed, what they become is manual, and renaming
    onto a name already in use merges into it.
    """

    async def test_the_tag_is_renamed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        response = await client.patch(
            "/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"}
        )

        assert response.status_code == 204
        assert [t["tag"] for t in (await client.get("/users/1/tags", headers=AUTH)).json()] == [
            "fiction"
        ]

    async def test_the_items_carry_the_new_name(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["tags"] == [{"tag": "fiction"}]

    async def test_every_item_that_carried_it_is_a_new_version(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """The only thing that tells a syncing client its items changed."""
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        untouched = await make_item(session, library, key="CCCC2345")
        await tag_item(session, library, one, "ficton")
        await tag_item(session, library, two, "ficton")
        before = (await client.get("/users/1/items/CCCC2345", headers=AUTH)).json()["version"]

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        assert untouched is not None
        changed = (await client.get("/users/1/items?since=10", headers=AUTH)).json()
        assert sorted(entry["key"] for entry in changed) == ["AAAA2345", "BBBB2345"]
        assert (await client.get("/users/1/items/CCCC2345", headers=AUTH)).json()[
            "version"
        ] == before

    async def test_the_client_s_own_timestamp_is_left_alone(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """The client did not do this, so `dateModified` is not the client's."""
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")
        before = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        after = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert after["data"]["dateModified"] == before["data"]["dateModified"]

    async def test_both_types_of_the_name_are_renamed(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "ficton", tag_type=0)
        await tag_item(session, library, two, "ficton", tag_type=1)

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        assert [t["tag"] for t in (await client.get("/users/1/tags", headers=AUTH)).json()] == [
            "fiction"
        ]

    async def test_what_it_becomes_is_manual(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """`Zotero.Tags.rename` sets `type=0` on every link it moves."""
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton", tag_type=1)

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["tags"] == [{"tag": "fiction"}]

    async def test_renaming_onto_an_existing_name_merges(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "ficton")
        await tag_item(session, library, one, "fiction")
        await tag_item(session, library, two, "ficton")

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        tags = (await client.get("/users/1/tags", headers=AUTH)).json()
        assert [t["tag"] for t in tags] == ["fiction"]
        assert tags[0]["meta"]["numItems"] == 2
        body = (await client.get("/users/1/items/AAAA2345", headers=AUTH)).json()
        assert body["data"]["tags"] == [{"tag": "fiction"}]

    async def test_it_merges_with_an_automatic_tag_of_that_name_too(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """The new name must end up naming one tag, whatever type it was.

        A name can be two tags here, because the type is on the tag rather than
        on its attachment to an item. The client has it the other way round --
        one row per name, the type on the link -- so its rename cannot leave a
        second tag with the same name, and neither can this.
        """
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "ficton", tag_type=0)
        await tag_item(session, library, two, "fiction", tag_type=1)

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        tags = (await client.get("/users/1/tags", headers=AUTH)).json()
        assert [(t["tag"], t["meta"]["type"]) for t in tags] == [("fiction", 0)]
        assert tags[0]["meta"]["numItems"] == 2

    async def test_an_absorbed_automatic_tag_leaves_its_items_manual(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """And their JSON changed, so they are a new version like the rest."""
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "ficton", tag_type=0)
        await tag_item(session, library, two, "fiction", tag_type=1)

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        body = (await client.get("/users/1/items/BBBB2345", headers=AUTH)).json()
        assert body["data"]["tags"] == [{"tag": "fiction"}]
        assert body["version"] == 11

    async def test_four_tags_of_two_names_become_one(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        for index, (key, name, tag_type) in enumerate(
            [
                ("AAAA2345", "ficton", 0),
                ("BBBB2345", "ficton", 1),
                ("CCCC2345", "fiction", 0),
                ("DDDD2345", "fiction", 1),
            ]
        ):
            assert index >= 0
            item = await make_item(session, library, key=key)
            await tag_item(session, library, item, name, tag_type=tag_type)

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        tags = (await client.get("/users/1/tags", headers=AUTH)).json()
        assert [(t["tag"], t["meta"]["type"], t["meta"]["numItems"]) for t in tags] == [
            ("fiction", 0, 4)
        ]

    async def test_an_item_already_under_the_new_name_is_left_where_it_is(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """Nothing changed for it, so it is not a new version."""
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "ficton")
        await tag_item(session, library, two, "fiction")

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        untouched = (await client.get("/users/1/items/BBBB2345", headers=AUTH)).json()
        assert untouched["version"] == 1
        assert untouched["data"]["tags"] == [{"tag": "fiction"}]

    async def test_the_old_name_is_reported_as_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()
        assert body["tags"] == ["ficton"]

    async def test_a_name_that_comes_back_stops_being_deleted(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        """Otherwise one sync says "remove this tag" and "here it is" at once."""
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"})
        version = int(
            (await client.get("/users/1/tags", headers=AUTH)).headers["Last-Modified-Version"]
        )
        await client.patch(
            "/users/1/tags/fiction",
            headers=AUTH | {"If-Unmodified-Since-Version": str(version)},
            json={"tag": "ficton"},
        )

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()
        assert body["tags"] == ["fiction"]

    async def test_one_request_is_one_new_version(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        one = await make_item(session, library, key="AAAA2345")
        two = await make_item(session, library, key="BBBB2345")
        await tag_item(session, library, one, "ficton")
        await tag_item(session, library, two, "ficton")

        response = await client.patch(
            "/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"}
        )

        assert response.headers["Last-Modified-Version"] == "11"

    async def test_the_name_it_already_has_changes_nothing(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")

        response = await client.patch(
            "/users/1/tags/fiction", headers=VERSIONED, json={"tag": " fiction "}
        )

        assert response.status_code == 204
        assert response.headers["Last-Modified-Version"] == "10"

    async def test_an_unknown_tag_is_not_found(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.patch(
            "/users/1/tags/ficton", headers=VERSIONED, json={"tag": "fiction"}
        )

        assert response.status_code == 404

    async def test_an_empty_name_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        response = await client.patch(
            "/users/1/tags/ficton", headers=VERSIONED, json={"tag": "   "}
        )

        assert response.status_code == 400

    async def test_an_absurd_name_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        response = await client.patch(
            "/users/1/tags/ficton", headers=VERSIONED, json={"tag": "x" * 256}
        )

        assert response.status_code == 400

    async def test_a_body_without_a_name_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        response = await client.patch("/users/1/tags/ficton", headers=VERSIONED, json={})

        assert response.status_code == 400

    async def test_the_version_header_is_required(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        response = await client.patch("/users/1/tags/ficton", headers=JSON, json={"tag": "fiction"})

        assert response.status_code == 428

    async def test_a_stale_version_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "ficton")

        response = await client.patch(
            "/users/1/tags/ficton",
            headers=AUTH | {"If-Unmodified-Since-Version": "9"},
            json={"tag": "fiction"},
        )

        assert response.status_code == 412
        assert [t["tag"] for t in (await client.get("/users/1/tags", headers=AUTH)).json()] == [
            "ficton"
        ]


class TestDeleteLog:
    async def test_since_is_required(self, client: httpx.AsyncClient, library: Library) -> None:
        assert (await client.get("/users/1/deleted", headers=AUTH)).status_code == 400

    async def test_an_empty_log_reports_every_group(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        body = (await client.get("/users/1/deleted?since=0", headers=AUTH)).json()

        assert body == {
            "collections": [],
            "items": [],
            "searches": [],
            "settings": [],
            "tags": [],
        }

    async def test_a_deleted_item_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        await client.delete("/users/1/items/AAAA2345", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["items"] == ["AAAA2345"]

    async def test_a_deleted_collection_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_collection(session, library, key="AAAA2345")
        await client.delete("/users/1/collections/AAAA2345", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["collections"] == ["AAAA2345"]

    async def test_a_deleted_search_is_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_search(session, library, key="AAAA2345")
        await client.delete("/users/1/searches/AAAA2345", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["searches"] == ["AAAA2345"]

    async def test_a_deleted_tag_is_reported_by_name(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        item = await make_item(session, library, key="AAAA2345")
        await tag_item(session, library, item, "fiction")
        await client.delete("/users/1/tags?tag=fiction", headers=VERSIONED)

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["tags"] == ["fiction"]

    async def test_older_deletions_are_not_reported(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        await make_item(session, library, key="AAAA2345")
        response = await client.delete("/users/1/items/AAAA2345", headers=VERSIONED)
        version = int(response.headers["Last-Modified-Version"])

        body = (await client.get(f"/users/1/deleted?since={version}", headers=AUTH)).json()

        assert body["items"] == []

    async def test_deleting_the_same_key_twice_yields_one_entry(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library
    ) -> None:
        # The dataserver keys this table on (library, type, key), so a repeat
        # moves the existing row forward instead of adding a second one.
        await make_item(session, library, key="AAAA2345")
        await client.delete("/users/1/items/AAAA2345", headers=VERSIONED)

        await make_item(session, library, key="AAAA2345")
        latest = (await client.get("/users/1/items", headers=AUTH)).headers["Last-Modified-Version"]
        await client.delete(
            "/users/1/items/AAAA2345",
            headers=AUTH | {"If-Unmodified-Since-Version": latest},
        )

        body = (await client.get("/users/1/deleted?since=10", headers=AUTH)).json()

        assert body["items"] == ["AAAA2345"]
