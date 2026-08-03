"""The web interface's endpoints, against PostgreSQL rather than SQLite.

The rest of the web tests run on SQLite, which is the default deployment and
the fast one. That is not enough on its own: SQLite accepts things PostgreSQL
refuses, and the difference is invisible until somebody runs the container
image, which uses PostgreSQL.

This file exists because of one such difference that reached a real deployment.
``pending_for_user`` compared the address column against ``"\\0"`` for an
account that has none -- an impossible value, chosen so the clause could never
match. SQLite stores a NUL in a string without complaint; PostgreSQL answers
``invalid byte sequence for encoding "UTF8": 0x00`` and the notifications panel
returned 500 for every account made by `altero user add`. The whole suite was
green, because every test account had been created through registration, which
requires an address.

So the cases here are deliberately the ones the SQLite tests do not reach:
accounts without an address, and the endpoints that query on it.

Skipped without ``ALTERO_TEST_POSTGRES_URL``; CI supplies one and fails if
anything skipped.
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest

from altero.app import create_app
from altero.db import Base, Database
from altero.services import admin, invitations, notifications, webauth
from altero.settings import Settings

POSTGRES_URL = os.environ.get("ALTERO_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ALTERO_TEST_POSTGRES_URL is not set")

PASSWORD = "correct horse battery staple"


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    assert POSTGRES_URL
    database = Database(Settings(database_url=POSTGRES_URL))
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest.fixture
async def client(database: Database) -> AsyncIterator[httpx.AsyncClient]:
    assert POSTGRES_URL
    app = create_app(Settings(database_url=POSTGRES_URL))
    app.state.database = database
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def make_cli_account(database: Database, username: str = "ada"):  # type: ignore[no-untyped-def]
    """Create an account the way `altero user add` does: no email address."""
    async with database.session_factory() as session:
        user = await admin.create_user(session, username=username, display_name="Ada")
        await webauth.set_password(session, user, PASSWORD)
        return user.id


async def sign_in(client: httpx.AsyncClient, username: str = "ada") -> None:
    response = await client.post(
        "/web/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("altero_csrf") or ""}


class TestAnAccountWithNoAddress:
    """`altero user add` makes these, and they have no email at all."""

    async def test_the_notifications_panel_answers(
        self, client: httpx.AsyncClient, database: Database
    ) -> None:
        """This is the regression. It answered 500 on PostgreSQL."""
        await make_cli_account(database)
        await sign_in(client)

        response = await client.get("/web/notifications")

        assert response.status_code == 200
        assert response.json() == {"unread": 0, "notifications": [], "invitations": []}

    async def test_the_account_page_answers(
        self, client: httpx.AsyncClient, database: Database
    ) -> None:
        await make_cli_account(database)
        await sign_in(client)

        response = await client.get("/web/account")

        assert response.status_code == 200
        assert response.json()["user"]["email"] is None
        assert response.json()["user"]["emailVerified"] is False

    async def test_they_can_still_be_invited_by_link(
        self, client: httpx.AsyncClient, database: Database
    ) -> None:
        """Matched on the invitation's user_id, since there is no address to match."""
        await make_cli_account(database)

        async with database.session_factory() as session:
            grace = await webauth.register(
                session,
                username="grace",
                password=PASSWORD,
                email="grace@example.org",
                allow_registration=True,
            )
            library = await admin.create_group(
                session, name="Analytical Engine", owner_username="grace"
            )
            ada = await admin.get_user_by_name(session, "ada")
            invitation, _ = await invitations.invite_with_token(
                session, library=library, inviter=grace, email="ada-elsewhere@example.org"
            )
            # Linked by hand, as accepting an emailed link would do.
            invitation.user_id = ada.id
            await session.commit()
            await notifications.raise_for(
                session,
                ada,
                kind="invitation",
                subject="Grace invited you",
                invitation_id=invitation.id,
            )

        await sign_in(client)
        body = (await client.get("/web/notifications")).json()

        assert body["unread"] == 1
        assert [entry["libraryName"] for entry in body["invitations"]] == ["Analytical Engine"]

    async def test_they_can_answer_that_invitation(
        self, client: httpx.AsyncClient, database: Database
    ) -> None:
        await make_cli_account(database)

        async with database.session_factory() as session:
            grace = await webauth.register(
                session,
                username="grace",
                password=PASSWORD,
                email="grace@example.org",
                allow_registration=True,
            )
            library = await admin.create_group(
                session, name="Analytical Engine", owner_username="grace"
            )
            ada = await admin.get_user_by_name(session, "ada")
            invitation, _ = await invitations.invite_with_token(
                session, library=library, inviter=grace, email="ada-elsewhere@example.org"
            )
            invitation.user_id = ada.id
            await session.commit()
            invitation_id = invitation.id

        await sign_in(client)
        response = await client.post(
            f"/web/invitations/{invitation_id}/accept", headers=csrf(client)
        )

        assert response.status_code == 200
        assert len((await client.get("/web/libraries")).json()) == 2


class TestTheOrdinaryPathsAlsoWorkHere:
    """Cheap insurance: the same flows the SQLite tests cover, on PostgreSQL."""

    async def test_register_sign_in_and_read_the_library(self, client: httpx.AsyncClient) -> None:
        registered = await client.post(
            "/web/auth/register",
            json={
                "username": "ada",
                "password": PASSWORD,
                "email": "ada@example.org",
                "displayName": "Ada",
            },
        )

        assert registered.status_code == 201
        assert (await client.get("/web/auth/session")).status_code == 200
        assert (await client.get("/web/notifications")).json()["unread"] == 0
        assert len((await client.get("/web/libraries")).json()) == 1

    async def test_an_invitation_round_trip(
        self, client: httpx.AsyncClient, database: Database
    ) -> None:
        await client.post(
            "/web/auth/register",
            json={"username": "ada", "password": PASSWORD, "email": "ada@example.org"},
        )

        async with database.session_factory() as session:
            grace = await webauth.register(
                session,
                username="grace",
                password=PASSWORD,
                email="grace@example.org",
                allow_registration=True,
            )
            library = await admin.create_group(
                session, name="Analytical Engine", owner_username="grace"
            )
            invitation = await invitations.invite(
                session, library=library, inviter=grace, email="ada@example.org"
            )
            invitation_id = invitation.id

        body = (await client.get("/web/notifications")).json()
        assert body["unread"] == 1

        accepted = await client.post(
            f"/web/invitations/{invitation_id}/accept", headers=csrf(client)
        )

        assert accepted.status_code == 200
        assert (await client.get("/web/notifications")).json()["unread"] == 0
        assert len((await client.get("/web/libraries")).json()) == 2


class TestTheFileProtocol:
    """Uploads, which are where PostgreSQL's stricter integers bite.

    Zotero sends `mtime` as milliseconds since the epoch. That has not fitted
    in a 32-bit integer since January 1970, so a column typed INTEGER takes it
    on SQLite -- whose INTEGER is 64-bit -- and refuses it on PostgreSQL with
    "value out of int32 range". Every file upload against the container image
    failed for that reason while the whole suite stayed green.
    """

    #: A real millisecond timestamp, as the desktop client sends. Well past
    #: 2**31, which is the entire point of it.
    MTIME = 1785793739415

    async def test_authorising_an_upload_accepts_a_millisecond_mtime(
        self, client: httpx.AsyncClient, database: Database
    ) -> None:
        await client.post(
            "/web/auth/register",
            json={"username": "ada", "password": PASSWORD, "email": "ada@example.org"},
        )
        async with database.session_factory() as session:
            api_key = await admin.create_api_key(session, username="ada", name="client")
            key = api_key.key

        created = await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key},
            json=[
                {"itemType": "book", "title": "Parent"},
            ],
        )
        parent = created.json()["successful"]["0"]["key"]
        attachment = await client.post(
            "/users/1/items",
            headers={"Zotero-API-Key": key},
            json=[
                {
                    "itemType": "attachment",
                    "parentItem": parent,
                    "linkMode": "imported_url",
                    "title": "PDF",
                    "filename": "paper.pdf",
                    "contentType": "application/pdf",
                }
            ],
        )
        attachment_key = attachment.json()["successful"]["0"]["key"]

        response = await client.post(
            f"/users/1/items/{attachment_key}/file",
            headers={
                "Zotero-API-Key": key,
                "Content-Type": "application/x-www-form-urlencoded",
                "If-None-Match": "*",
            },
            content=(
                f"mtime={self.MTIME}&md5=82faf4c7774556f4877d8f258def124e"
                "&filename=paper.pdf&filesize=2586902"
            ),
        )

        assert response.status_code == 200, response.text
        assert response.json()["uploadKey"]
