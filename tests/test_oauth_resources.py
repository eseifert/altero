"""An OAuth grant confined to particular libraries and collections.

The feature is one ceiling added to :func:`altero.services.auth.access_for` and
one predicate added to the item query, so almost everything here is an attempt
to reach past it by some other door: a listing, a key, a version, a count, a
search, an export, the full-text index, a child item, the delete log, the tag
list, a write. Each class below names the door it tries.

The two shapes that must keep working are held as well: a grant nobody narrowed
behaves exactly as it did before this existed, and a refreshed token is still
the same authorization.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.app import create_app
from altero.models import Collection, Item, Library, LibraryType, OAuthGrant, OAuthGrantResource
from altero.services import auth, oauthserver
from altero.services import items as items_service
from altero.settings import Settings
from tests.factories import (
    index_fulltext,
    make_collection,
    make_group,
    make_item,
    make_search,
    tag_item,
)
from tests.test_oauth import (
    PASSWORD,
    PUBLIC_URL,
    authorize,
    bearer,
    code_from,
    csrf,
    make_client,
    pkce,
)

# --------------------------------------------------------------------------
# A library laid out so that every kind of leak has something to leak
# --------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        storage_path=tmp_path / "storage",
        public_url=PUBLIC_URL,
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    await application.state.database.create_all()
    yield application
    await application.state.database.dispose()


class Fixture:
    """What every test here works against, named so assertions read as prose."""

    def __init__(self) -> None:
        self.user_id: int = 0
        self.personal: Library
        self.granted: Collection
        self.nested: Collection
        self.sibling: Collection
        self.granted_item: Item
        self.nested_item: Item
        self.sibling_item: Item
        self.unfiled_item: Item
        self.granted_note: Item
        self.sibling_note: Item
        self.granted_attachment: Item
        self.sibling_attachment: Item
        self.allowed_group: Library
        self.denied_group: Library
        self.allowed_group_item: Item
        self.denied_group_item: Item
        self.group_collection: Collection


async def register(client: httpx.AsyncClient, username: str = "ada") -> int:
    response = await client.post(
        "/web/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "email": f"{username}@example.org",
            "displayName": "Ada Lovelace",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["user"]["id"])


async def build(session: AsyncSession, client: httpx.AsyncClient) -> Fixture:
    """Lay out a personal library and two groups.

    The personal library holds three collections -- one granted, one nested
    inside it, one sibling -- and an unfiled item beside them. Every collection
    holds an item, and the granted and sibling items each carry a note and an
    attachment, so that a child item can be asked about from either side of the
    line.
    """
    state = Fixture()
    state.user_id = await register(client)

    personal = await session.scalar(
        select(Library).where(Library.type == LibraryType.USER, Library.owner_id == state.user_id)
    )
    assert personal is not None
    state.personal = personal

    state.granted_item = await make_item(session, personal, fields={"title": "Granted paper"})
    state.nested_item = await make_item(session, personal, fields={"title": "Nested paper"})
    state.sibling_item = await make_item(session, personal, fields={"title": "Sibling paper"})
    state.unfiled_item = await make_item(session, personal, fields={"title": "Unfiled paper"})

    state.granted = await make_collection(
        session, personal, name="Reading", items=[state.granted_item]
    )
    state.nested = await make_collection(
        session, personal, name="Reading/2026", parent=state.granted, items=[state.nested_item]
    )
    state.sibling = await make_collection(
        session, personal, name="Teaching", items=[state.sibling_item]
    )

    state.granted_note = await make_item(
        session, personal, item_type="note", parent=state.granted_item
    )
    state.sibling_note = await make_item(
        session, personal, item_type="note", parent=state.sibling_item
    )
    state.granted_attachment = await make_item(
        session,
        personal,
        item_type="attachment",
        parent=state.granted_item,
        fields={"linkMode": "linked_url", "url": "https://example.org/granted"},
    )
    state.sibling_attachment = await make_item(
        session,
        personal,
        item_type="attachment",
        parent=state.sibling_item,
        fields={"linkMode": "linked_url", "url": "https://example.org/sibling"},
    )

    await tag_item(session, personal, state.granted_item, "inside")
    await tag_item(session, personal, state.sibling_item, "outside")
    await make_search(session, personal, name="Everything")

    state.allowed_group = await make_group(
        session, group_id=42, owner_id=state.user_id, name="Allowed"
    )
    state.denied_group = await make_group(
        session, group_id=99, owner_id=state.user_id, name="Denied"
    )
    state.allowed_group_item = await make_item(
        session, state.allowed_group, fields={"title": "Allowed group paper"}
    )
    state.denied_group_item = await make_item(
        session, state.denied_group, fields={"title": "Denied group paper"}
    )
    state.group_collection = await make_collection(
        session, state.allowed_group, name="Shared", items=[state.allowed_group_item]
    )

    return state


ALL_SCOPES = (
    "openid groups library.read library.write notes.read files.read groups.read groups.write"
)


async def token_for(
    client: httpx.AsyncClient,
    *,
    resources: list[str] | None,
    scope: str = "openid library.read notes.read files.read groups.read",
) -> dict:
    """Walk the whole flow, narrowing the grant to ``resources``, and return the tokens."""
    verifier, challenge = pkce()
    started = await authorize(client, challenge=challenge, scope=scope)
    handle = started.headers["location"].split("request=")[1]

    decided = await client.post(
        f"/web/oauth/pending/{handle}",
        json={"approve": True, "resources": resources},
        headers=csrf(client),
    )
    assert decided.status_code == 200, decided.text

    tokens = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "notebook",
            "code": code_from(decided.json()["redirect"]),
            "code_verifier": verifier,
            "redirect_uri": "https://app.example.com/callback",
        },
    )
    assert tokens.status_code == 200, tokens.text
    return tokens.json()


@pytest.fixture
async def library(session: AsyncSession, client: httpx.AsyncClient) -> Fixture:
    await make_client(session, scopes=ALL_SCOPES)
    return await build(session, client)


def keys(payload: list[dict]) -> set[str]:
    return {entry["key"] for entry in payload}


# --------------------------------------------------------------------------
# 1. One group allowed, another denied
# --------------------------------------------------------------------------


class TestOneGroupAndNotAnother:
    """A grant naming group 42 reaches group 42 and no other library."""

    async def test_the_named_group_is_readable(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=["groups/42"])

        response = await client.get("/groups/42/items", headers=bearer(tokens["access_token"]))

        assert response.status_code == 200
        assert keys(response.json()) == {library.allowed_group_item.key}

    async def test_another_group_is_refused(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=["groups/42"])

        response = await client.get("/groups/99/items", headers=bearer(tokens["access_token"]))

        assert response.status_code == 403

    async def test_the_owners_own_library_is_refused(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """A grant naming a group names *only* it, the personal library included.

        The library somebody owns is the one a scope-only grant reaches first,
        so this is the case where forgetting the ceiling would be least visible.
        """
        tokens = await token_for(client, resources=["groups/42"])

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 403

    async def test_the_group_listing_names_only_the_granted_one(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """``GET /users/<id>/groups`` is the first request of every sync.

        Left alone it hands an application the id, name and description of every
        group its owner is in, which is the whole of what a per-group grant was
        made to prevent.
        """
        tokens = await token_for(client, resources=["groups/42"])

        response = await client.get(
            f"/users/{library.user_id}/groups", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 200
        assert [entry["id"] for entry in response.json()] == [42]

    async def test_the_group_versions_form_names_only_the_granted_one(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=["groups/42"])

        response = await client.get(
            f"/users/{library.user_id}/groups",
            params={"format": "versions"},
            headers=bearer(tokens["access_token"]),
        )

        assert list(response.json()) == ["42"]

    async def test_the_denied_group_is_not_described(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """``GET /groups/<id>`` answers 404 for a library the grant does not name.

        Not 403: which private groups exist is not something a refusal should
        confirm, and that is already how a stranger to a group is answered.
        """
        tokens = await token_for(client, resources=["groups/42"])

        response = await client.get("/groups/99", headers=bearer(tokens["access_token"]))

        assert response.status_code == 404

    async def test_the_groups_claim_names_only_the_granted_one(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client, resources=["groups/42"], scope="openid groups library.read"
        )

        response = await client.get("/oauth/userinfo", headers=bearer(tokens["access_token"]))

        assert response.json()["groups"] == ["Allowed"]


# --------------------------------------------------------------------------
# 2 and 4. One collection, its siblings, and what nesting means
# --------------------------------------------------------------------------


class TestOneCollectionAndNotItsSiblings:
    """A grant naming a collection reaches that branch and nothing beside it."""

    async def test_the_granted_item_is_listed(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/items/top", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 200
        assert keys(response.json()) == {library.granted_item.key, library.nested_item.key}

    async def test_a_sibling_collections_item_is_not(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert library.sibling_item.key not in keys(response.json())

    async def test_an_unfiled_item_is_not(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """Filed nowhere is inside no collection, so it is inside no grant."""
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert library.unfiled_item.key not in keys(response.json())

    async def test_a_nested_collections_items_come_along(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """Naming a collection means the branch. See ``confinement_for``."""
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/collections/{library.nested.key}/items",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 200
        assert keys(response.json()) == {library.nested_item.key}

    async def test_naming_the_nested_collection_does_not_reach_its_parent(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The branch goes downwards only."""
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.nested.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert keys(response.json()) == {library.nested_item.key}

    async def test_the_collection_listing_shows_only_the_branch(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/collections", headers=bearer(tokens["access_token"])
        )

        assert keys(response.json()) == {library.granted.key, library.nested.key}

    async def test_a_granted_collection_nested_deep_is_still_top_level(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """``/collections/top`` means top *of what the caller can see*.

        The granted collection has a parent the grant does not name, so asking
        the stored tree would put it under something invisible and leave it out
        of every listing there is.
        """
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.nested.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/collections/top", headers=bearer(tokens["access_token"])
        )

        assert keys(response.json()) == {library.nested.key}

    async def test_a_sibling_collection_is_not_found_by_key(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/collections/{library.sibling.key}",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 404

    async def test_a_sibling_collections_items_are_not_found_either(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """Not an empty page: an empty page says the collection is there."""
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/collections/{library.sibling.key}/items",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 404


# --------------------------------------------------------------------------
# 3. The same rules in a group library
# --------------------------------------------------------------------------


class TestACollectionOfAGroupLibrary:
    async def test_a_group_collection_confines_the_group(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        loose = await make_item(
            session, library.allowed_group, fields={"title": "Not in the collection"}
        )
        tokens = await token_for(
            client, resources=[f"groups/42/collections/{library.group_collection.key}"]
        )

        response = await client.get("/groups/42/items", headers=bearer(tokens["access_token"]))

        assert keys(response.json()) == {library.allowed_group_item.key}
        assert loose.key not in keys(response.json())

    async def test_a_personal_and_a_group_grant_hold_together(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """Two libraries, narrowed differently, in one grant."""
        tokens = await token_for(
            client,
            resources=[
                f"users/{library.user_id}/collections/{library.granted.key}",
                "groups/42",
            ],
        )
        token = tokens["access_token"]

        personal = await client.get(f"/users/{library.user_id}/items", headers=bearer(token))
        group = await client.get("/groups/42/items", headers=bearer(token))
        denied = await client.get("/groups/99/items", headers=bearer(token))

        assert library.sibling_item.key not in keys(personal.json())
        assert library.allowed_group_item.key in keys(group.json())
        assert denied.status_code == 403

    async def test_a_library_named_entire_is_not_narrowed_by_a_collection_row(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The wider row wins, so the order the rows went in cannot decide."""
        loose = await make_item(session, library.allowed_group, fields={"title": "Loose"})
        tokens = await token_for(
            client,
            resources=[
                f"groups/42/collections/{library.group_collection.key}",
                "groups/42",
            ],
        )

        response = await client.get("/groups/42/items", headers=bearer(tokens["access_token"]))

        assert loose.key in keys(response.json())

    async def test_a_group_the_owner_is_not_in_cannot_be_granted(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """A grant narrows what its owner can do; it is never a way past it."""
        from tests.factories import make_user

        await make_user(session, user_id=999, username="grace", display_name="Grace Hopper")
        outside = await make_group(session, group_id=7, owner_id=999, name="Somebody else's")
        assert outside.owner_id == 7

        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid groups.read")
        handle = started.headers["location"].split("request=")[1]

        response = await client.post(
            f"/web/oauth/pending/{handle}",
            json={"approve": True, "resources": ["groups/7"]},
            headers=csrf(client),
        )

        assert response.status_code == 400
        assert verifier


# --------------------------------------------------------------------------
# 5. Reading and writing
# --------------------------------------------------------------------------


class TestReadingAndWriting:
    """Write is the scope *and* the grant, and never one of the two."""

    async def test_an_item_inside_the_grant_can_be_written(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.patch(
            f"/users/{library.user_id}/items/{library.granted_item.key}",
            json={"title": "Renamed"},
            headers={
                **bearer(tokens["access_token"]),
                "If-Unmodified-Since-Version": str(library.granted_item.version),
            },
        )

        assert response.status_code == 204, response.text

    async def test_an_item_outside_the_grant_cannot_be(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """404, not 403. A write must not confirm what a read would not."""
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.patch(
            f"/users/{library.user_id}/items/{library.sibling_item.key}",
            json={"title": "Renamed"},
            headers={
                **bearer(tokens["access_token"]),
                "If-Unmodified-Since-Version": str(library.sibling_item.version),
            },
        )

        assert response.status_code == 404

    async def test_an_item_cannot_be_walked_out_of_the_grant(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """Refiling into a collection outside the grant is refused.

        Allowing it would let an application empty the collection it was given
        one item at a time, and lose sight of each item as it went.
        """
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.patch(
            f"/users/{library.user_id}/items/{library.granted_item.key}",
            json={"collections": [library.sibling.key]},
            headers={
                **bearer(tokens["access_token"]),
                "If-Unmodified-Since-Version": str(library.granted_item.version),
            },
        )

        assert response.status_code == 403

    async def test_a_new_item_must_land_inside_the_grant(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.post(
            f"/users/{library.user_id}/items",
            json=[{"itemType": "book", "title": "Filed nowhere"}],
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 200
        assert response.json()["failed"], response.text

    async def test_a_new_item_filed_inside_the_grant_is_accepted(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.post(
            f"/users/{library.user_id}/items",
            json=[
                {
                    "itemType": "book",
                    "title": "Filed here",
                    "collections": [library.granted.key],
                }
            ],
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 200
        assert response.json()["successful"], response.text

    async def test_the_librarys_shape_is_read_only(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """No collection, saved search, setting or tag is writable under a grant.

        None of them belongs to a collection, so there is no part of them the
        grant was given. See ``Access.may_change_structure``.
        """
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.post(
            f"/users/{library.user_id}/collections",
            json=[{"name": "New"}],
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 200
        assert response.json()["failed"], response.text

    async def test_renaming_a_tag_refuses_the_same_way_whether_it_exists(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The refusal must not tell a confined token which tags are there.

        Found by driving a real server: the route looked the tag up before
        asking the permission, so a tag carried only outside the grant answered
        403 while a name nobody had used answered 404 -- which is the library's
        tag list, one guess at a time.
        """
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )
        headers = {
            **bearer(tokens["access_token"]),
            "If-Unmodified-Since-Version": "100",
        }

        outside = await client.patch(
            f"/users/{library.user_id}/tags/outside", json={"tag": "later"}, headers=headers
        )
        absent = await client.patch(
            f"/users/{library.user_id}/tags/nosuchtag", json={"tag": "later"}, headers=headers
        )

        assert outside.status_code == 404
        assert absent.status_code == 404

    async def test_deleting_a_search_or_setting_answers_the_same_either_way(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The same 403-versus-404 leak the tag rename had, in two more routes.

        A confined grant sees no saved searches and no settings, so a key or a
        name it may not have must answer 404 whether or not something is stored
        under it.
        """
        from altero.models import Setting

        stored = await make_search(session, library.personal, name="Another")
        session.add(
            Setting(library_id=library.personal.id, name="tagColors", value="[]", version=1)
        )
        await session.commit()

        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )
        headers = {
            **bearer(tokens["access_token"]),
            "If-Unmodified-Since-Version": "100",
        }

        for path in (
            f"/users/{library.user_id}/searches/{stored.key}",
            f"/users/{library.user_id}/searches/AAAAAAAA",
            f"/users/{library.user_id}/settings/tagColors",
            f"/users/{library.user_id}/settings/nosuchsetting",
        ):
            response = await client.delete(path, headers=headers)
            assert response.status_code == 404, f"{path} answered {response.status_code}"

    async def test_renaming_a_tag_it_can_see_is_still_refused(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """A tag inside the grant is refused for what it would rewrite.

        Renaming rewrites every item carrying the tag, including the ones
        outside the grant, so the answer is the confinement rather than 404 --
        the token already knows this tag exists.
        """
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.patch(
            f"/users/{library.user_id}/tags/inside",
            json={"tag": "later"},
            headers={
                **bearer(tokens["access_token"]),
                "If-Unmodified-Since-Version": "100",
            },
        )

        assert response.status_code == 403

    async def test_a_confined_grant_does_not_administer_a_group(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """A group's membership is the group's shape, like its collections.

        A grant to one collection is not a grant to decide who is in the group.
        """
        tokens = await token_for(
            client,
            resources=[f"groups/42/collections/{library.group_collection.key}"],
            scope="openid groups.read groups.write",
        )

        response = await client.post(
            "/groups/42/users",
            json={"userID": library.user_id, "role": "member"},
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 403

    async def test_a_confined_grant_does_not_make_a_new_group(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.post(
            "/groups",
            json={"name": "New group"},
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 403

    async def test_an_unconfined_grant_still_administers_a_group(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The line is the confinement and nothing else."""
        tokens = await token_for(client, resources=None, scope="openid groups.read groups.write")

        response = await client.patch(
            "/groups/42",
            json={"name": "Renamed"},
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 200, response.text

    async def test_a_read_only_grant_still_cannot_write_inside_it(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The grant never widens the scope. ``library.write`` was not asked for."""
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read",
        )

        response = await client.patch(
            f"/users/{library.user_id}/items/{library.granted_item.key}",
            json={"title": "Renamed"},
            headers={
                **bearer(tokens["access_token"]),
                "If-Unmodified-Since-Version": str(library.granted_item.version),
            },
        )

        assert response.status_code == 403

    async def test_deleting_something_outside_the_grant_is_not_found(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read library.write",
        )

        response = await client.delete(
            f"/users/{library.user_id}/items/{library.sibling_item.key}",
            headers={
                **bearer(tokens["access_token"]),
                "If-Unmodified-Since-Version": "100",
            },
        )

        assert response.status_code == 404


# --------------------------------------------------------------------------
# 6. Notes and files, inside the grant
# --------------------------------------------------------------------------


class TestNotesAndFilesStillApply:
    """The scopes narrow what is left after the grant, never the other way."""

    async def test_a_note_inside_the_grant_is_reachable_with_the_scope(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read notes.read",
        )

        response = await client.get(
            f"/users/{library.user_id}/items/{library.granted_note.key}",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 200

    async def test_a_note_inside_the_grant_is_withheld_without_the_scope(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read",
        )

        response = await client.get(
            f"/users/{library.user_id}/items/{library.granted_note.key}",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 404

    async def test_a_note_outside_the_grant_is_withheld_even_with_the_scope(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read notes.read",
        )

        response = await client.get(
            f"/users/{library.user_id}/items/{library.sibling_note.key}",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 404

    async def test_the_child_count_agrees_with_both(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """``numChildren`` is the last thing that can say a hidden child exists."""
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read",
        )

        response = await client.get(
            f"/users/{library.user_id}/items/{library.granted_item.key}",
            headers=bearer(tokens["access_token"]),
        )

        # The attachment, and not the note the scope withholds.
        assert response.json()["meta"]["numChildren"] == 1

    async def test_a_file_outside_the_grant_is_not_found(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read files.read",
        )

        response = await client.get(
            f"/users/{library.user_id}/items/{library.sibling_attachment.key}/file",
            headers=bearer(tokens["access_token"]),
        )

        assert response.status_code == 404


# --------------------------------------------------------------------------
# 7. Every other way to ask
# --------------------------------------------------------------------------


class TestNothingLeaksThroughAnIndirectPath:
    """A count, a key, a version, a search, an export, a log, a child."""

    @pytest.fixture
    async def token(self, client: httpx.AsyncClient, library: Fixture) -> str:
        tokens = await token_for(
            client,
            resources=[f"users/{library.user_id}/collections/{library.granted.key}"],
            scope="openid library.read notes.read files.read",
        )
        return str(tokens["access_token"])

    async def test_the_total_counts_only_what_is_reachable(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(f"/users/{library.user_id}/items", headers=bearer(token))

        assert response.status_code == 200
        # Two filed items, plus the granted item's note and attachment.
        assert response.headers["Total-Results"] == "4"

    async def test_the_key_listing_names_only_what_is_reachable(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        """``format=keys`` is unpaginated, so a leak here is the whole library."""
        response = await client.get(
            f"/users/{library.user_id}/items",
            params={"format": "keys"},
            headers=bearer(token),
        )

        assert set(response.text.split()) == {
            library.granted_item.key,
            library.nested_item.key,
            library.granted_note.key,
            library.granted_attachment.key,
        }

    async def test_the_version_listing_does_too(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(
            f"/users/{library.user_id}/items",
            params={"format": "versions"},
            headers=bearer(token),
        )

        assert library.sibling_item.key not in response.json()

    async def test_a_search_cannot_reach_outside(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(
            f"/users/{library.user_id}/items",
            params={"q": "Sibling", "qmode": "everything"},
            headers=bearer(token),
        )

        assert response.json() == []

    async def test_a_search_that_matches_a_hidden_child_surfaces_no_parent(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        """The ``/top`` mapping finds parents through children; it is confined too."""
        await index_fulltext(session, library.personal, library.sibling_attachment, "quantum")

        response = await client.get(
            f"/users/{library.user_id}/items/top",
            params={"q": "quantum", "qmode": "everything"},
            headers=bearer(token),
        )

        assert response.json() == []

    async def test_an_export_holds_only_what_the_listing_held(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(
            f"/users/{library.user_id}/items",
            params={"format": "bibtex"},
            headers=bearer(token),
        )

        assert "Sibling paper" not in response.text
        assert "Granted paper" in response.text

    async def test_the_full_text_index_names_only_reachable_items(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        await index_fulltext(session, library.personal, library.granted_attachment, "inside")
        await index_fulltext(session, library.personal, library.sibling_attachment, "outside")

        response = await client.get(f"/users/{library.user_id}/fulltext", headers=bearer(token))

        assert set(response.json()) == {library.granted_attachment.key}

    async def test_the_full_text_of_an_item_outside_is_not_found(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        await index_fulltext(session, library.personal, library.sibling_attachment, "outside")

        response = await client.get(
            f"/users/{library.user_id}/items/{library.sibling_attachment.key}/fulltext",
            headers=bearer(token),
        )

        assert response.status_code == 404

    async def test_the_children_of_an_item_outside_are_not_found(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(
            f"/users/{library.user_id}/items/{library.sibling_item.key}/children",
            headers=bearer(token),
        )

        assert response.status_code == 404

    async def test_the_children_of_an_item_inside_are_found(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(
            f"/users/{library.user_id}/items/{library.granted_item.key}/children",
            headers=bearer(token),
        )

        assert keys(response.json()) == {
            library.granted_note.key,
            library.granted_attachment.key,
        }

    async def test_the_tag_listing_counts_only_reachable_items(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(f"/users/{library.user_id}/tags", headers=bearer(token))

        assert {entry["tag"] for entry in response.json()} == {"inside"}

    async def test_a_tag_carried_only_outside_is_not_found(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(f"/users/{library.user_id}/tags/outside", headers=bearer(token))

        assert response.status_code == 404

    async def test_the_saved_searches_are_not_listed(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        """A saved search reaches wherever its conditions reach. See ``list_searches``."""
        response = await client.get(f"/users/{library.user_id}/searches", headers=bearer(token))

        assert response.json() == []

    async def test_the_settings_are_not_listed(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        response = await client.get(f"/users/{library.user_id}/settings", headers=bearer(token))

        assert response.json() == {}

    async def test_the_delete_log_says_nothing(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        """What is left of a deleted object is its key, and the key alone."""
        response = await client.get(
            f"/users/{library.user_id}/deleted",
            params={"since": 0},
            headers=bearer(token),
        )

        assert response.json() == {
            "collections": [],
            "items": [],
            "searches": [],
            "settings": [],
            "tags": [],
        }

    async def test_the_trash_shows_only_what_is_reachable(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        library.sibling_item.deleted = True
        library.granted_item.deleted = True
        await session.commit()

        response = await client.get(f"/users/{library.user_id}/items/trash", headers=bearer(token))

        assert library.granted_item.key in keys(response.json())
        assert library.sibling_item.key not in keys(response.json())

    async def test_the_unfiled_view_is_empty(
        self, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        """Unfiled means in no collection, which means in no grant."""
        response = await client.get(
            f"/users/{library.user_id}/items/top",
            params={"itemKey": library.unfiled_item.key},
            headers=bearer(token),
        )

        assert response.json() == []

    async def test_the_publications_view_keeps_its_notes(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        """My Publications answers with no credential, so it withholds no notes.

        The ``Access`` computed for the library says ``notes=library.public``
        for an anonymous caller, which for an ordinary private library is
        ``False`` -- and taking that as the answer would empty every published
        note out of a view whose whole point is that a stranger can read it.
        See ``publications.published_permit``.
        """
        library.granted_item.in_publications = True
        library.granted_note.in_publications = True
        await session.commit()

        anonymous = await client.get(f"/users/{library.user_id}/publications/items")

        assert anonymous.status_code == 200
        assert library.granted_note.key in keys(anonymous.json())

    async def test_the_publications_view_is_confined_too(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture, token: str
    ) -> None:
        library.sibling_item.in_publications = True
        library.granted_item.in_publications = True
        await session.commit()

        response = await client.get(
            f"/users/{library.user_id}/publications/items", headers=bearer(token)
        )

        assert library.granted_item.key in keys(response.json())
        assert library.sibling_item.key not in keys(response.json())


# --------------------------------------------------------------------------
# 8. A refreshed token is the same authorization
# --------------------------------------------------------------------------


class TestARefreshedTokenKeepsTheGrant:
    async def test_the_confinement_survives_a_refresh(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The restriction is on the grant, so it cannot be waited out.

        Had it lived on the access token, an application would only have to
        refresh once to be rid of it.
        """
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        refreshed = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "notebook",
                "refresh_token": tokens["refresh_token"],
            },
        )
        assert refreshed.status_code == 200, refreshed.text

        response = await client.get(
            f"/users/{library.user_id}/items",
            headers=bearer(refreshed.json()["access_token"]),
        )

        assert library.sibling_item.key not in keys(response.json())

    async def test_a_refreshed_group_grant_survives_too(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=["groups/42"])

        refreshed = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "notebook",
                "refresh_token": tokens["refresh_token"],
            },
        )

        response = await client.get(
            "/groups/99/items", headers=bearer(refreshed.json()["access_token"])
        )

        assert response.status_code == 403


# --------------------------------------------------------------------------
# 9. Nothing changes for a grant nobody narrowed
# --------------------------------------------------------------------------


class TestAnUnrestrictedGrantIsUnchanged:
    async def test_no_resources_reaches_the_whole_library(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=None)

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert library.sibling_item.key in keys(response.json())
        assert library.unfiled_item.key in keys(response.json())

    async def test_an_empty_list_is_the_same_as_none(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """A screen that offered the choice and had nothing ticked narrows nothing."""
        tokens = await token_for(client, resources=[])

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert library.sibling_item.key in keys(response.json())

    async def test_the_grant_row_is_not_marked_restricted(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        await token_for(client, resources=None)

        grant = await session.scalar(select(OAuthGrant))
        assert grant is not None
        assert grant.restricted is False

    async def test_an_unrestricted_grant_still_sees_every_group(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=None, scope="openid groups.read")

        response = await client.get(
            f"/users/{library.user_id}/groups", headers=bearer(tokens["access_token"])
        )

        assert {entry["id"] for entry in response.json()} == {42, 99}

    async def test_an_api_key_is_untouched(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """No API key can carry a resource grant, and none is affected by one.

        The shared authorization layer changed; what a key means did not.
        """
        from tests.factories import make_api_key

        await make_api_key(session, user_id=library.user_id, all_groups_read=True)

        response = await client.get(
            f"/users/{library.user_id}/items",
            headers={"Zotero-API-Key": "P9NiFoyLeZu2bZNvvuQPDWsd"},
        )

        assert library.sibling_item.key in keys(response.json())
        assert library.unfiled_item.key in keys(response.json())


# --------------------------------------------------------------------------
# Revocation, replacement, and what happens to the rows
# --------------------------------------------------------------------------


class TestRevokingAndReplacing:
    async def test_approving_again_replaces_the_resources(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """A consent screen answers about the whole grant, not about a delta.

        Otherwise an application could accumulate collections by asking often
        enough, which is exactly the thing consent is supposed to stop.
        """
        await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.sibling.key}"]
        )

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert library.sibling_item.key in keys(response.json())
        assert library.granted_item.key not in keys(response.json())

    async def test_lifting_the_confinement_works(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )
        tokens = await token_for(client, resources=None)

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert library.sibling_item.key in keys(response.json())

    async def test_revoking_takes_the_resources_with_it(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        tokens = await token_for(client, resources=["groups/42"])

        listed = await client.get("/web/oauth/authorizations")
        grant_id = listed.json()[0]["id"]
        removed = await client.delete(f"/web/oauth/authorizations/{grant_id}", headers=csrf(client))
        assert removed.status_code == 204

        rows = list(await session.scalars(select(OAuthGrantResource)))
        assert rows == []

        refused = await client.get("/groups/42/items", headers=bearer(tokens["access_token"]))
        assert refused.status_code == 403

    async def test_deleting_a_granted_collection_narrows_rather_than_widens(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The ``restricted`` flag outlives the rows, and this is why it exists.

        Reading the row count instead would turn deleting the last granted
        collection into a silent promotion to the whole account.
        """
        tokens = await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        await session.execute(delete(OAuthGrantResource))
        await session.commit()

        response = await client.get(
            f"/users/{library.user_id}/items", headers=bearer(tokens["access_token"])
        )

        assert response.status_code == 403


# --------------------------------------------------------------------------
# The consent screen
# --------------------------------------------------------------------------


class TestTheConsentScreen:
    async def test_it_offers_the_libraries_and_their_collections(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        verifier, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid library.read")
        handle = started.headers["location"].split("request=")[1]

        response = await client.get(f"/web/oauth/pending/{handle}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["reachesLibraries"] is True
        offered = {entry["id"]: entry for entry in payload["libraries"]}
        assert set(offered) == {f"users/{library.user_id}", "groups/42", "groups/99"}
        assert {entry["name"] for entry in offered[f"users/{library.user_id}"]["collections"]} == {
            "Reading",
            "Reading/2026",
            "Teaching",
        }
        assert verifier

    async def test_it_nests_the_collections(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid library.read")
        handle = started.headers["location"].split("request=")[1]

        payload = (await client.get(f"/web/oauth/pending/{handle}")).json()
        personal = next(
            entry for entry in payload["libraries"] if entry["id"] == f"users/{library.user_id}"
        )
        nested = next(entry for entry in personal["collections"] if entry["name"] == "Reading/2026")

        assert nested["parentKey"] == library.granted.key

    async def test_it_offers_nothing_when_no_library_is_asked_for(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """An application asking only to establish identity reaches no library.

        Offering to confine it to a collection would be a promise about nothing.
        """
        _, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid")
        handle = started.headers["location"].split("request=")[1]

        payload = (await client.get(f"/web/oauth/pending/{handle}")).json()

        assert payload["reachesLibraries"] is False
        assert payload["libraries"] == []

    async def test_it_says_what_a_standing_grant_already_reaches(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        await token_for(
            client, resources=[f"users/{library.user_id}/collections/{library.granted.key}"]
        )

        _, challenge = pkce()
        started = await authorize(client, challenge=challenge, scope="openid library.read")
        handle = started.headers["location"].split("request=")[1]
        payload = (await client.get(f"/web/oauth/pending/{handle}")).json()

        assert payload["restricted"] is True
        assert payload["grantedResources"] == [
            {
                "library": f"users/{library.user_id}",
                "libraryName": "Ada Lovelace",
                "collectionKey": library.granted.key,
                "collectionName": "Reading",
            }
        ]

    async def test_the_authorization_listing_says_so_too(
        self, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        await token_for(client, resources=["groups/42"])

        listed = await client.get("/web/oauth/authorizations")

        entry = listed.json()[0]
        assert entry["restricted"] is True
        assert entry["resources"] == [
            {
                "library": "groups/42",
                "libraryName": "Allowed",
                "collectionKey": None,
                "collectionName": None,
            }
        ]


# --------------------------------------------------------------------------
# The two forms of the predicate cannot disagree
# --------------------------------------------------------------------------


class TestTheItemPredicateHasOneMeaning:
    async def test_the_query_and_the_single_item_form_agree(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """``confined_to_collections`` and ``in_collections`` are one rule twice.

        A listing that filters one way and a lookup by key that filters another
        is exactly how an item becomes reachable by key and invisible in every
        listing -- or the reverse, which is the leak.
        """
        confined = await auth._with_descendants(
            session, library.personal, frozenset({library.granted.id})
        )

        listed = set(
            await session.scalars(
                select(Item.id).where(
                    Item.library_id == library.personal.id,
                    items_service.confined_to_collections(confined),
                )
            )
        )
        everything = list(
            await session.scalars(select(Item).where(Item.library_id == library.personal.id))
        )

        one_at_a_time = {
            item.id
            for item in everything
            if await items_service.in_collections(session, item, confined)
        }

        assert listed == one_at_a_time
        assert listed == {
            library.granted_item.id,
            library.nested_item.id,
            library.granted_note.id,
            library.granted_attachment.id,
        }

    async def test_an_annotation_under_a_filed_item_is_inside(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """Three levels is as deep as Zotero nests, and the predicate reaches it."""
        annotation = await make_item(
            session,
            library.personal,
            item_type="annotation",
            parent=library.granted_attachment,
            fields={"annotationType": "highlight", "annotationText": "inside"},
        )
        confined = await auth._with_descendants(
            session, library.personal, frozenset({library.granted.id})
        )

        assert await items_service.in_collections(session, annotation, confined)

    async def test_a_grant_cannot_name_a_collection_of_another_library(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        """The library is restated in the widening query, so a stray id cannot widen.

        The ids come from a row rather than from a request, but the row outlives
        the collection it names and a primary key gets reused.
        """
        widened = await auth._with_descendants(
            session, library.personal, frozenset({library.group_collection.id})
        )

        assert widened == frozenset()


# --------------------------------------------------------------------------
# The confinement is resolved once, and only when there is one
# --------------------------------------------------------------------------


class TestResolvingTheConfinement:
    async def test_an_unrestricted_credential_costs_no_query(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        credential = auth.Credential(user_id=library.user_id, library_read=True)

        assert await auth.confinement_for(session, library.personal, credential) is None

    async def test_a_library_the_grant_does_not_name_is_denied(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        credential = auth.Credential(
            user_id=library.user_id,
            library_read=True,
            resources=auth.ResourceGrant(libraries=frozenset({library.allowed_group.id})),
        )

        confinement = await auth.confinement_for(session, library.personal, credential)

        assert confinement is not None
        assert confinement.denied is True

    async def test_a_library_named_entire_is_not_confined(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        credential = auth.Credential(
            user_id=library.user_id,
            library_read=True,
            resources=auth.ResourceGrant(libraries=frozenset({library.personal.id})),
        )

        confinement = await auth.confinement_for(session, library.personal, credential)

        assert confinement is not None
        assert confinement.denied is False
        assert confinement.collections is None

    async def test_a_denied_library_reads_nothing_and_writes_nothing(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        credential = auth.Credential(
            user_id=library.user_id,
            library_read=True,
            library_write=True,
            resources=auth.ResourceGrant(libraries=frozenset({library.allowed_group.id})),
        )

        access = await auth.get_access(session, library.personal, credential)

        assert access.read is False
        assert access.write is False
        assert access.notes is False
        assert access.files is False

    async def test_offered_resources_never_names_a_library_out_of_reach(
        self, session: AsyncSession, client: httpx.AsyncClient, library: Fixture
    ) -> None:
        from tests.factories import make_user

        await make_user(session, user_id=999, username="grace", display_name="Grace Hopper")
        await make_group(session, group_id=7, owner_id=999, name="Somebody else's")
        from altero.models import User

        user = await session.get(User, library.user_id)
        assert user is not None

        offered = await oauthserver.offered_resources(session, user)

        assert {entry.id for entry in offered} == {
            f"users/{library.user_id}",
            "groups/42",
            "groups/99",
        }
