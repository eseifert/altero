"""Profile pages -- ``/web/profiles/<username>``.

The public face of My Publications, and the only part of ``/web`` that answers
a request carrying no cookie. What it may show is the owner's decision:
``public`` is upstream's behaviour and the default, ``users`` limits the page
to accounts on this instance, and ``private`` leaves the items published but
the page unreadable by anyone but their owner.

A profile that may not be read answers 404, the same as a name nobody holds.
Anything else would let a stranger ask which usernames exist here.
"""

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import Item, Library, LibraryType, ProfileVisibility, User
from altero.services import storage
from altero.services.auth import get_library
from tests.factories import make_item, make_user
from tests.test_web_routes import PASSWORD, csrf_headers, register


async def _store(
    session: AsyncSession,
    app: FastAPI,
    library: Library,
    *,
    key: str,
    content: bytes,
    in_publications: bool = False,
) -> Item:
    """Create an attachment and put its bytes where the server keeps them."""
    digest = hashlib.md5(content, usedforsecurity=False).hexdigest()
    item = await make_item(
        session,
        library,
        key=key,
        item_type="attachment",
        fields={
            "linkMode": "imported_file",
            "filename": "paper.txt",
            "contentType": "text/plain",
            "md5": digest,
        },
        in_publications=in_publications,
    )

    path = storage.file_path(Path(app.state.settings.storage_path), digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return item


@pytest.fixture
async def owner(session: AsyncSession) -> User:
    """An account with a published book, a private one and two children."""
    user = await make_user(session, user_id=1, username="ada", display_name="Ada Lovelace")
    library = await get_library(session, LibraryType.USER, 1)

    published = await make_item(
        session,
        library,
        key="PUBLIC01",
        fields={"title": "Notes on the Analytical Engine", "date": "1843"},
        creators=[("author", "Ada", "Lovelace")],
        in_publications=True,
    )
    await make_item(session, library, key="PRIVATE1", fields={"title": "Unfinished"})
    await make_item(
        session,
        library,
        key="NOTE0001",
        item_type="note",
        parent=published,
        fields={"note": "A published note"},
        in_publications=True,
    )
    await make_item(
        session,
        library,
        key="NOTE0002",
        item_type="note",
        parent=published,
        fields={"note": "A note left behind"},
    )
    return user


@pytest.fixture
async def library(session: AsyncSession, owner: User) -> Library:
    return await get_library(session, LibraryType.USER, owner.id)


async def set_visibility(session: AsyncSession, owner: User, visibility: ProfileVisibility) -> None:
    owner.profile_visibility = visibility
    await session.commit()


async def sign_in_as(client: httpx.AsyncClient, session: AsyncSession, username: str) -> User:
    """Put a second account on this instance and sign the browser in as it.

    Not `register`: registration closes once an account exists, and the
    fixtures here make theirs directly. This is the `altero user add` path,
    which is how every account after the first arrives anyway.
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


class TestReadingAProfile:
    async def test_a_stranger_sees_a_public_profile(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        response = await client.get("/web/profiles/ada")

        assert response.status_code == 200
        assert response.json()["displayName"] == "Ada Lovelace"
        assert response.json()["numPublications"] == 1

    async def test_the_username_stands_in_for_a_missing_display_name(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """`Zotero_Users::getName` falls back the same way."""
        owner.display_name = ""
        await session.commit()

        response = await client.get("/web/profiles/ada")

        assert response.json()["displayName"] == "ada"

    async def test_the_name_is_matched_without_regard_to_case(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        assert (await client.get("/web/profiles/Ada")).status_code == 200

    async def test_a_slugged_name_arrives(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """`Zotero_Utilities::slugify` turns a space into an underscore."""
        await make_user(session, user_id=2, username="Ada Lovelace")

        response = await client.get("/web/profiles/ada_lovelace")

        assert response.status_code == 200
        assert response.json()["username"] == "Ada Lovelace"

    async def test_an_unclaimed_name_is_absent(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/web/profiles/nobody")).status_code == 404

    async def test_a_stranger_is_not_told_whose_profile_it_is(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        """`owner` and `visibility` are the reader's own business, never anyone's."""
        payload = (await client.get("/web/profiles/ada")).json()

        assert payload["owner"] is False
        assert payload["visibility"] is None


class TestWhatIsOnThePage:
    async def test_only_published_items_are_listed(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        listing = await client.get("/web/profiles/ada/items")

        keys = {entry["key"] for entry in listing.json()["items"]}
        assert keys == {"PUBLIC01"}

    async def test_an_unpublished_item_is_absent_by_key_too(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        """Hiding it from the listing is pointless if its key still fetches it."""
        response = await client.get("/web/profiles/ada/items/PRIVATE1")

        assert response.status_code == 404

    async def test_a_trashed_publication_is_absent(
        self, client: httpx.AsyncClient, session: AsyncSession, library: Library, owner: User
    ) -> None:
        trashed = await make_item(
            session, library, key="TRASHED1", in_publications=True, deleted=True
        )
        assert trashed.deleted

        listing = await client.get("/web/profiles/ada/items")
        one = await client.get("/web/profiles/ada/items/TRASHED1")

        assert "TRASHED1" not in {entry["key"] for entry in listing.json()["items"]}
        assert one.status_code == 404

    async def test_only_the_children_that_were_published_come_along(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        """The wizard answered that question once; a note left behind stays behind."""
        response = await client.get("/web/profiles/ada/items/PUBLIC01/children")

        keys = {entry["key"] for entry in response.json()["items"]}
        assert keys == {"NOTE0001"}

    async def test_an_item_carries_the_shape_the_library_view_uses(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        item = (await client.get("/web/profiles/ada/items/PUBLIC01")).json()

        assert item["key"] == "PUBLIC01"
        assert item["data"]["title"] == "Notes on the Analytical Engine"
        assert item["meta"]["creatorSummary"] == "Lovelace"

    async def test_a_citation_can_be_had_for_a_published_item(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        response = await client.get("/web/profiles/ada/items/PUBLIC01/citation")

        assert response.status_code == 200
        assert "Lovelace" in response.json()["bib"]

    async def test_a_citation_is_refused_for_an_unpublished_one(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        assert (await client.get("/web/profiles/ada/items/PRIVATE1/citation")).status_code == 404


class TestPublishedFiles:
    """What the licence question in the publishing wizard was about."""

    async def test_a_published_file_is_served_to_a_stranger(
        self,
        client: httpx.AsyncClient,
        session: AsyncSession,
        library: Library,
        owner: User,
        app: FastAPI,
    ) -> None:
        await _store(
            session,
            app,
            library,
            key="FILE0001",
            content=b"the paper",
            in_publications=True,
        )

        response = await client.get("/web/profiles/ada/items/FILE0001/file")

        assert response.status_code == 200
        assert response.text == "the paper"

    async def test_it_can_be_asked_for_as_a_download(
        self,
        client: httpx.AsyncClient,
        session: AsyncSession,
        library: Library,
        owner: User,
        app: FastAPI,
    ) -> None:
        await _store(
            session, app, library, key="FILE0003", content=b"the paper", in_publications=True
        )

        response = await client.get("/web/profiles/ada/items/FILE0003/file?download=true")

        assert "paper.txt" in response.headers["content-disposition"]

    async def test_an_unpublished_file_is_not(
        self,
        client: httpx.AsyncClient,
        session: AsyncSession,
        library: Library,
        owner: User,
        app: FastAPI,
    ) -> None:
        """An item published without its files has none here."""
        await _store(session, app, library, key="FILE0002", content=b"a draft")

        response = await client.get("/web/profiles/ada/items/FILE0002/file")

        assert response.status_code == 404


class TestWhoMaySee:
    async def test_users_only_refuses_a_stranger(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        await set_visibility(session, owner, ProfileVisibility.USERS)

        assert (await client.get("/web/profiles/ada")).status_code == 404

    async def test_users_only_admits_somebody_signed_in(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        await set_visibility(session, owner, ProfileVisibility.USERS)
        await sign_in_as(client, session, "grace")

        assert (await client.get("/web/profiles/ada")).status_code == 200

    async def test_private_refuses_another_account(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        await set_visibility(session, owner, ProfileVisibility.PRIVATE)
        await sign_in_as(client, session, "grace")

        assert (await client.get("/web/profiles/ada")).status_code == 404

    async def test_the_owner_always_sees_their_own_page(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Otherwise closing the page means losing the way to check what is on it."""
        await register(client, username="ada")
        user = await session.get(User, 1)
        assert user is not None
        await set_visibility(session, user, ProfileVisibility.PRIVATE)

        response = await client.get("/web/profiles/ada")

        assert response.status_code == 200
        assert response.json()["owner"] is True
        assert response.json()["visibility"] == "private"

    async def test_the_items_are_hidden_with_the_page(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """Every endpoint asks, not only the one that draws the heading."""
        await set_visibility(session, owner, ProfileVisibility.PRIVATE)

        for path in (
            "/web/profiles/ada/items",
            "/web/profiles/ada/items/PUBLIC01",
            "/web/profiles/ada/items/PUBLIC01/children",
            "/web/profiles/ada/items/PUBLIC01/citation",
            "/web/profiles/ada/items/PUBLIC01/file",
        ):
            assert (await client.get(path)).status_code == 404, path


class TestTheSetting:
    async def test_an_account_starts_public(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Which is the behaviour every account had before the setting existed."""
        await register(client)

        user = await session.get(User, 1)
        assert user is not None
        assert user.profile_visibility is ProfileVisibility.PUBLIC

    async def test_the_session_reports_it(self, client: httpx.AsyncClient) -> None:
        response = await register(client)

        assert response.json()["user"]["profileVisibility"] == "public"

    async def test_it_can_be_changed(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)

        response = await client.patch(
            "/web/account",
            json={"profileVisibility": "users"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 200
        assert response.json()["user"]["profileVisibility"] == "users"

    async def test_a_display_name_can_still_be_changed_on_its_own(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.patch(
            "/web/account", json={"displayName": "Ada L"}, headers=csrf_headers(client)
        )

        assert response.status_code == 200
        assert response.json()["user"]["displayName"] == "Ada L"
        assert response.json()["user"]["profileVisibility"] == "public"

    async def test_a_value_that_is_not_one_of_the_three_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.patch(
            "/web/account",
            json={"profileVisibility": "everyone-i-like"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400

    async def test_it_takes_a_csrf_token_like_every_other_write(
        self, client: httpx.AsyncClient
    ) -> None:
        await register(client)

        response = await client.patch("/web/account", json={"profileVisibility": "private"})

        assert response.status_code == 403


class TestTheBoundaryStillHolds:
    async def test_an_api_key_reaches_no_profile_page(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """It is answered, but the key is not what answered it.

        A profile is public; the point is that presenting a key neither grants
        anything here nor is looked at. A private profile stays private to it.
        """
        from altero.services import admin

        key = await admin.create_api_key(session, username="ada", name="laptop")
        await set_visibility(session, owner, ProfileVisibility.PRIVATE)

        response = await client.get("/web/profiles/ada", headers={"Zotero-API-Key": key.key})

        assert response.status_code == 404

    async def test_the_password_is_not_needed_to_read_a_public_page(
        self, client: httpx.AsyncClient, owner: User
    ) -> None:
        assert PASSWORD  # the fixture account has none; nothing here asks for one
        assert (await client.get("/web/profiles/ada/items")).status_code == 200


class TestFindingTheAccount:
    """How a name in the address reaches an account.

    Upstream forms a profile link from the username through
    `Zotero_Utilities::slugify`, so both forms have to arrive here.
    """

    async def test_a_name_that_could_be_nobodys_slug_is_answered_at_once(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """Nothing slugs to a string holding what slugify drops.

        Which is what keeps a mistyped address off the pass over every account.
        """
        from altero.services import profiles

        assert profiles.slugify("Ada Lovelace!") == "ada_lovelace"
        assert (await client.get("/web/profiles/Ada%20Lovelace!")).status_code == 404

    async def test_the_username_wins_over_a_slug_that_matches(
        self, client: httpx.AsyncClient, session: AsyncSession, owner: User
    ) -> None:
        """Two accounts can share a slug; the one actually named it is meant."""
        await make_user(session, user_id=2, username="ada_lovelace")
        await make_user(session, user_id=3, username="Ada Lovelace")

        response = await client.get("/web/profiles/ada_lovelace")

        assert response.json()["username"] == "ada_lovelace"


class TestTheColumnsDefault:
    """The value a row gets when nothing writes the column.

    Which is every row that existed before the column did: the migration adds
    it with a default, and those rows carry that default until somebody opens
    the setting. It has to be the string SQLAlchemy itself writes -- the
    enum's *name*, ``PUBLIC``, not its value -- or reading such a row back
    raises `LookupError: 'public' is not among the defined enum values` and
    signing in answers 500.
    """

    async def test_a_row_that_never_wrote_the_column_reads_back(
        self, session: AsyncSession
    ) -> None:
        await session.execute(
            text("INSERT INTO users (id, username, display_name) VALUES (2, 'grace', '')")
        )
        await session.commit()

        user = await session.get(User, 2)

        assert user is not None
        assert user.profile_visibility is ProfileVisibility.PUBLIC

    async def test_the_migration_writes_the_same_default_the_model_does(self) -> None:
        """The two are set in different files and must not drift apart."""
        column = User.__table__.c.profile_visibility
        assert column.server_default is not None
        assert column.server_default.arg == ProfileVisibility.PUBLIC.name
