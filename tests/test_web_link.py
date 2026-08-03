"""Linking the Zotero desktop client from the browser.

The client starts a login session, opens a page, and polls until that page has
been approved. Until now the approving happened at a shell prompt. This is the
same exchange, answered in the interface instead.

The thing being handed over is a full-access API key, which is a larger grant
than reading one's own library, so it is not something a signed-in tab should
be able to do by being pointed at a URL. Approving therefore takes the password
again, the way every other credential change in the account does.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import admin
from altero.services import login as login_service
from tests.test_web_routes import csrf_headers, register

PASSWORD = "correct horse battery staple"


async def start_session(client: httpx.AsyncClient, user_id: int | None = None) -> str:
    """Do what the desktop client does first, and return its session token."""
    body = {"userID": user_id} if user_id is not None else {}
    response = await client.post("/keys/sessions", json=body)
    assert response.status_code == 201
    return response.json()["sessionToken"]


class TestThePageTheClientOpens:
    async def test_it_sends_a_browser_to_the_interface(
        self, client: httpx.AsyncClient, as_if_built: object
    ) -> None:
        """The client opens loginURL in a browser; that is where the flow lives."""
        token = await start_session(client)

        response = await client.get(f"/keys/sessions/{token}/login")

        assert response.status_code in (302, 303, 307)
        assert response.headers["location"] == f"/app/link?token={token}"

    async def test_an_unknown_session_is_still_a_404(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/keys/sessions/nope/login")).status_code == 404


class TestReadingTheRequest:
    async def test_it_describes_a_pending_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        token = await start_session(client)

        body = (await client.get(f"/web/link/{token}")).json()

        assert body["status"] == "pending"
        assert body["canApprove"] is True
        assert body["requestedUserId"] is None
        assert body["expiresInSeconds"] > 0

    async def test_it_needs_a_session(self, client: httpx.AsyncClient) -> None:
        """Otherwise the page would say what exists before anyone has signed in."""
        token = await start_session(client)

        assert (await client.get(f"/web/link/{token}")).status_code == 401

    async def test_an_unknown_token_is_a_404(self, client: httpx.AsyncClient) -> None:
        await register(client)

        assert (await client.get("/web/link/nope")).status_code == 404

    async def test_a_session_for_another_account_cannot_be_approved(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The client named the account it expects.

        Handing it a different user's key makes the desktop application treat
        the library as belonging to somebody else: checkUser sees a changed
        userID, offers to reset the data directory and quits. So this is
        refused before it can be approved, with a reason the page can show.
        """
        await register(client)
        grace = await admin.create_user(session, username="grace")
        token = await start_session(client, user_id=grace.id)

        body = (await client.get(f"/web/link/{token}")).json()

        assert body["canApprove"] is False
        assert body["requestedUserId"] == grace.id
        assert "grace" in body["reason"] or str(grace.id) in body["reason"]

    async def test_it_reports_a_session_already_answered(self, client: httpx.AsyncClient) -> None:
        await register(client)
        token = await start_session(client)
        await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        body = (await client.get(f"/web/link/{token}")).json()

        assert body["status"] == "completed"
        assert body["canApprove"] is False


class TestApproving:
    async def test_the_client_gets_a_key(self, client: httpx.AsyncClient) -> None:
        """The whole exchange, end to end, as the client performs it."""
        await register(client)
        token = await start_session(client)

        approved = await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        assert approved.status_code == 204

        polled = (await client.get(f"/keys/sessions/{token}")).json()

        assert polled["status"] == "completed"
        assert polled["apiKey"]
        assert polled["userID"] == 1
        assert polled["username"] == "ada"

    async def test_the_key_can_actually_sync(self, client: httpx.AsyncClient) -> None:
        """A key that cannot read the library would be a working flow and a
        broken result."""
        await register(client)
        token = await start_session(client)
        await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        key = (await client.get(f"/keys/sessions/{token}")).json()["apiKey"]

        response = await client.get("/users/1/items", headers={"Zotero-API-Key": key})

        assert response.status_code == 200

    async def test_the_key_covers_group_libraries_too(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """The client syncs groups as well, and a key without them looks like
        a server that lost them."""
        await register(client)
        library = await admin.create_group(session, name="Analytical Engine", owner_username="ada")
        token = await start_session(client)
        await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )
        key = (await client.get(f"/keys/sessions/{token}")).json()["apiKey"]

        response = await client.get(
            f"/groups/{library.owner_id}/items", headers={"Zotero-API-Key": key}
        )

        assert response.status_code == 200

    async def test_the_wrong_password_approves_nothing(self, client: httpx.AsyncClient) -> None:
        await register(client)
        token = await start_session(client)

        response = await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": "not it"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403
        assert (await client.get(f"/keys/sessions/{token}")).json()["status"] == "pending"

    async def test_it_needs_the_csrf_token(self, client: httpx.AsyncClient) -> None:
        """A page elsewhere must not be able to make this happen."""
        await register(client)
        token = await start_session(client)

        response = await client.post(
            f"/web/link/{token}/approve", json={"currentPassword": PASSWORD}
        )

        assert response.status_code == 403
        assert (await client.get(f"/keys/sessions/{token}")).json()["status"] == "pending"

    async def test_it_needs_a_signed_in_session(self, client: httpx.AsyncClient) -> None:
        token = await start_session(client)

        response = await client.post(
            f"/web/link/{token}/approve", json={"currentPassword": PASSWORD}
        )

        assert response.status_code in (401, 403)

    async def test_approving_twice_is_refused(self, client: httpx.AsyncClient) -> None:
        await register(client)
        token = await start_session(client)
        await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        again = await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert again.status_code == 400

    async def test_a_session_naming_another_account_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        await register(client)
        grace = await admin.create_user(session, username="grace")
        token = await start_session(client, user_id=grace.id)

        response = await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 400
        assert (await client.get(f"/keys/sessions/{token}")).json()["status"] == "pending"

    async def test_an_expired_session_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        from datetime import UTC, datetime, timedelta

        await register(client)
        token = await start_session(client)
        record = await login_service.get_session(session, token)
        record.created = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            minutes=login_service.SESSION_LIFETIME_MINUTES + 1
        )
        await session.commit()

        response = await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert response.status_code == 404

    async def test_the_issued_key_is_recognisable_afterwards(
        self, client: httpx.AsyncClient, session: AsyncSession
    ) -> None:
        """Somebody revoking keys later has to be able to tell which is which."""
        await register(client)
        token = await start_session(client)
        await client.post(
            f"/web/link/{token}/approve",
            json={"currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        keys = await admin.list_api_keys(session)

        assert len(keys) == 1
        assert "Zotero" in keys[0].name


class TestDeclining:
    async def test_it_cancels_the_session(self, client: httpx.AsyncClient) -> None:
        await register(client)
        token = await start_session(client)

        response = await client.post(f"/web/link/{token}/deny", headers=csrf_headers(client))

        assert response.status_code == 204
        assert (await client.get(f"/keys/sessions/{token}")).json()["status"] == "cancelled"

    async def test_declining_needs_no_password(self, client: httpx.AsyncClient) -> None:
        """Refusing to grant something should never be harder than granting it."""
        await register(client)
        token = await start_session(client)

        assert (
            await client.post(f"/web/link/{token}/deny", headers=csrf_headers(client))
        ).status_code == 204

    async def test_it_still_needs_the_csrf_token(self, client: httpx.AsyncClient) -> None:
        await register(client)
        token = await start_session(client)

        assert (await client.post(f"/web/link/{token}/deny")).status_code == 403

    async def test_no_key_is_issued(self, client: httpx.AsyncClient, session: AsyncSession) -> None:
        await register(client)
        token = await start_session(client)

        await client.post(f"/web/link/{token}/deny", headers=csrf_headers(client))

        assert await admin.list_api_keys(session) == []
