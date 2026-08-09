"""``/users/<id>/publications`` — the public view of My Publications.

Read anonymously, which is the point of it: upstream's own test suite defaults
to ``API::useAPIKey("")`` for the whole file and expects 200. Only items flagged
``inPublications`` appear, and only ``items`` exists -- ``publications/collections``
and ``publications/searches`` answer 404.

There is no group equivalent. My Publications belongs to a person.
"""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Library, LibraryType, ProfileVisibility, User
from altero.services.auth import get_library
from tests.factories import make_api_key, make_item, make_user

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


@pytest.fixture
async def published(session: AsyncSession, library: Library) -> dict[str, Any]:
    """One published item, one private one, and a child of the published one."""
    public = await make_item(
        session, library, key="PUBLIC01", fields={"title": "Published"}, in_publications=True
    )
    await make_item(session, library, key="PRIVATE1", fields={"title": "Private"})
    await make_item(
        session,
        library,
        key="CHILD001",
        item_type="note",
        parent=public,
        fields={"note": "A note"},
        in_publications=True,
    )
    return {"public": "PUBLIC01", "private": "PRIVATE1", "child": "CHILD001"}


class TestReadingWithoutAKey:
    async def test_the_listing_is_anonymous(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        response = await client.get("/users/1/publications/items")

        assert response.status_code == 200
        assert response.headers["Last-Modified-Version"] == "10"

    async def test_only_published_items_appear(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        listing = await client.get("/users/1/publications/items")

        keys = {entry["key"] for entry in listing.json()}
        assert published["private"] not in keys
        assert published["public"] in keys

    async def test_an_empty_publications_list_is_not_an_error(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/publications/items")

        assert response.status_code == 200
        assert response.json() == []

    async def test_a_key_may_still_be_supplied(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        response = await client.get("/users/1/publications/items", headers=AUTH)

        assert response.status_code == 200

    async def test_top_excludes_children(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        listing = await client.get("/users/1/publications/items/top")

        assert [entry["key"] for entry in listing.json()] == [published["public"]]

    async def test_one_item_can_be_fetched(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        response = await client.get(f"/users/1/publications/items/{published['public']}")

        assert response.status_code == 200
        assert response.json()["data"]["title"] == "Published"

    async def test_a_private_item_is_not_reachable_by_key(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        # The listing hiding it would be no use if the key still fetched it.
        response = await client.get(f"/users/1/publications/items/{published['private']}")

        assert response.status_code == 404

    async def test_the_sync_formats_work(
        self, client: httpx.AsyncClient, published: dict[str, Any]
    ) -> None:
        versions = await client.get("/users/1/publications/items?format=versions")

        assert set(versions.json()) == {published["public"], published["child"]}


class TestTheRestOfTheSyncCycle:
    """The client polls these alongside the items, and stops on anything but a 200."""

    async def test_settings_are_empty_but_present(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/users/1/publications/settings")

        assert response.status_code == 200
        assert response.json() == []
        assert response.headers["Total-Results"] == "0"
        assert response.headers["Last-Modified-Version"] == str(library.version)

    async def test_deletions_are_an_empty_object(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        """An object, not an array: the shape a `/deleted` response has."""
        response = await client.get("/users/1/publications/deleted")

        assert response.status_code == 200
        assert response.json() == {}
        assert response.headers["Last-Modified-Version"] == str(library.version)

    async def test_both_are_readable_without_a_key(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        for path in ("settings", "deleted"):
            assert (await client.get(f"/users/1/publications/{path}")).status_code == 200


class TestWhatIsNotThere:
    @pytest.mark.parametrize("path", ["collections", "searches"])
    async def test_only_items_exist(
        self, client: httpx.AsyncClient, library: Library, path: str
    ) -> None:
        response = await client.get(f"/users/1/publications/{path}")

        assert response.status_code == 404

    async def test_writing_is_refused(self, client: httpx.AsyncClient, library: Library) -> None:
        # A public list is public to read, not to add to.
        response = await client.post(
            "/users/1/publications/items",
            headers=JSON,
            json=[{"itemType": "book", "title": "Dune"}],
        )

        assert response.status_code == 403

    async def test_a_group_has_no_publications(
        self, client: httpx.AsyncClient, library: Library
    ) -> None:
        response = await client.get("/groups/2/publications/items")

        assert response.status_code == 404


class TestTheOwnersVisibilitySetting:
    """altero's one addition here, and the reason it is not decorative.

    Upstream serves this list to anybody, full stop. altero lets the owner say
    who it is for, defaulting to upstream's answer -- and enforces that choice
    on these endpoints as well as on the profile page, because a page in the
    browser that refused a stranger while `curl` still listed the same work
    would be no setting at all.
    """

    @pytest.fixture
    async def owner(self, session: AsyncSession, library: Library) -> User:
        user = await session.get(User, 1)
        assert user is not None
        return user

    async def test_public_is_the_default_and_answers_a_stranger(
        self, client: httpx.AsyncClient, owner: User, published: dict[str, Any]
    ) -> None:
        assert owner.profile_visibility is ProfileVisibility.PUBLIC
        assert (await client.get("/users/1/publications/items")).status_code == 200

    async def test_users_refuses_a_caller_with_no_key(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        owner.profile_visibility = ProfileVisibility.USERS
        await session.commit()

        response = await client.get("/users/1/publications/items")

        assert response.status_code == 403

    async def test_users_admits_a_key_this_server_issued(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        owner.profile_visibility = ProfileVisibility.USERS
        await session.commit()

        response = await client.get("/users/1/publications/items", headers=AUTH)

        assert response.status_code == 200

    async def test_private_refuses_a_stranger(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        owner.profile_visibility = ProfileVisibility.PRIVATE
        await session.commit()

        assert (await client.get("/users/1/publications/items")).status_code == 403

    async def test_private_refuses_somebody_elses_key(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        owner.profile_visibility = ProfileVisibility.PRIVATE
        await session.commit()
        await make_user(session, user_id=2, username="grace")
        stranger = await make_api_key(session, key="ZZZZZZZZZZZZZZZZZZZZZZZZ", user_id=2)

        response = await client.get(
            "/users/1/publications/items", headers={"Zotero-API-Key": stranger.key}
        )

        assert response.status_code == 403

    async def test_the_owners_own_client_goes_on_syncing(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """Closing the page must not stop the desktop client reading its own list."""
        owner.profile_visibility = ProfileVisibility.PRIVATE
        await session.commit()

        assert (await client.get("/users/1/publications/items", headers=AUTH)).status_code == 200

    async def test_the_polls_the_client_makes_are_refused_too(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """Otherwise a closed list still reports its version to whoever asks."""
        owner.profile_visibility = ProfileVisibility.PRIVATE
        await session.commit()

        for path in ("settings", "deleted", "items/top"):
            assert (await client.get(f"/users/1/publications/{path}")).status_code == 403, path

    async def test_one_item_is_refused_by_key_as_well(
        self,
        client: httpx.AsyncClient,
        session: AsyncSession,
        owner: User,
        published: dict[str, Any],
    ) -> None:
        owner.profile_visibility = ProfileVisibility.PRIVATE
        await session.commit()

        response = await client.get(f"/users/1/publications/items/{published['public']}")

        assert response.status_code == 403
