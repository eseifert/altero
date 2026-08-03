"""The login flow the Zotero desktop client uses to obtain a key.

The sequence and the field names come from the client itself:
`chrome/content/zotero/xpcom/sync/syncAPIClient.js` and
`preferences_account.jsx` in zotero/zotero. The client refuses a completed
session that does not carry apiKey, userID and username, and polls until the
status is `completed` or `cancelled`.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from altero.services import admin, login
from tests.factories import make_api_key, make_user

KEY = "P9NiFoyLeZu2bZNvvuQPDWsd"


@pytest.fixture
async def user(session: AsyncSession) -> None:
    await make_user(session, user_id=1, username="octocat", display_name="Mona Lisa")
    await make_api_key(session, key=KEY, user_id=1)


class TestCurrentKey:
    async def test_the_current_key_describes_itself(
        self, client: httpx.AsyncClient, user: None
    ) -> None:
        # The first thing the client asks for after storing a key.
        response = await client.get("/keys/current", headers={"Zotero-API-Key": KEY})

        assert response.status_code == 200
        body = response.json()
        assert body["userID"] == 1
        assert body["username"] == "octocat"
        assert body["access"]["user"]["library"] is True

    async def test_an_unauthenticated_request_is_refused(
        self, client: httpx.AsyncClient, user: None
    ) -> None:
        assert (await client.get("/keys/current")).status_code == 403

    async def test_the_current_key_can_be_revoked(
        self, client: httpx.AsyncClient, user: None
    ) -> None:
        # This is what unlinking the account in the client does.
        response = await client.delete("/keys/current", headers={"Zotero-API-Key": KEY})

        assert response.status_code == 204
        assert (
            await client.get("/keys/current", headers={"Zotero-API-Key": KEY})
        ).status_code == 403


class TestLoginSession:
    async def test_a_session_returns_a_token_and_a_page(
        self, client: httpx.AsyncClient, user: None
    ) -> None:
        response = await client.post("/keys/sessions")

        assert response.status_code == 201
        body = response.json()
        assert body["sessionToken"]
        assert body["loginURL"].endswith(f"/keys/sessions/{body['sessionToken']}/login")

    async def test_a_fresh_session_is_pending(self, client: httpx.AsyncClient, user: None) -> None:
        token = (await client.post("/keys/sessions")).json()["sessionToken"]

        body = (await client.get(f"/keys/sessions/{token}")).json()

        assert body == {"status": "pending"}

    async def test_the_whole_flow_hands_the_client_a_key(
        self, client: httpx.AsyncClient, session: AsyncSession, user: None
    ) -> None:
        token = (await client.post("/keys/sessions")).json()["sessionToken"]

        api_key = await admin.create_api_key(session, username="octocat", name="Zotero")
        await login.approve_session(session, token, api_key)

        body = (await client.get(f"/keys/sessions/{token}")).json()

        # The client raises if any of the three is missing.
        assert body["status"] == "completed"
        assert body["apiKey"] == api_key.key
        assert body["userID"] == 1
        assert body["username"] == "octocat"

    async def test_the_login_page_sends_a_browser_to_the_interface(
        self, client: httpx.AsyncClient, user: None, as_if_built: object
    ) -> None:
        """With the interface built, the client's browser window lands on it."""
        token = (await client.post("/keys/sessions")).json()["sessionToken"]

        response = await client.get(f"/keys/sessions/{token}/login")

        assert response.status_code == 303
        assert response.headers["location"] == f"/app/link?token={token}"

    async def test_the_login_page_names_the_command_when_nothing_is_built(
        self, client: httpx.AsyncClient, user: None, as_if_not_built: None
    ) -> None:
        """A checkout with no frontend build must still be able to link a client.

        The API is entirely usable in that state, so sending the browser to a
        503 would be worse than a sentence somebody can act on.
        """
        token = (await client.post("/keys/sessions")).json()["sessionToken"]

        response = await client.get(f"/keys/sessions/{token}/login")

        assert response.status_code == 200
        assert f"altero login approve {token}" in response.text

    async def test_an_unknown_session_is_a_404(self, client: httpx.AsyncClient) -> None:
        # The client turns this into "Login session not found".
        assert (await client.get("/keys/sessions/nosuchtoken")).status_code == 404

    async def test_a_cancelled_session_reports_itself(
        self, client: httpx.AsyncClient, user: None
    ) -> None:
        token = (await client.post("/keys/sessions")).json()["sessionToken"]

        assert (await client.delete(f"/keys/sessions/{token}")).status_code == 204
        assert (await client.get(f"/keys/sessions/{token}")).json() == {"status": "cancelled"}

    async def test_cancelling_an_unknown_session_is_not_an_error(
        self, client: httpx.AsyncClient
    ) -> None:
        assert (await client.delete("/keys/sessions/nosuchtoken")).status_code == 204

    async def test_a_session_may_name_the_account_it_expects(
        self, client: httpx.AsyncClient, session: AsyncSession, user: None
    ) -> None:
        # The client sends its known userID when re-authenticating.
        token = (await client.post("/keys/sessions", json={"userID": 1})).json()["sessionToken"]

        api_key = await admin.create_api_key(session, username="octocat", name="Zotero")
        await login.approve_session(session, token, api_key)

        assert (await client.get(f"/keys/sessions/{token}")).json()["status"] == "completed"

    async def test_approving_with_another_users_key_is_refused(
        self, client: httpx.AsyncClient, session: AsyncSession, user: None
    ) -> None:
        # Attaching the library to the wrong account would be silent otherwise.
        await admin.create_user(session, username="other")
        token = (await client.post("/keys/sessions", json={"userID": 1})).json()["sessionToken"]
        other_key = await admin.create_api_key(session, username="other", name="Zotero")

        from altero.errors import InvalidInputError

        with pytest.raises(InvalidInputError, match="expects user 1"):
            await login.approve_session(session, token, other_key)

    async def test_a_session_cannot_be_approved_twice(
        self, client: httpx.AsyncClient, session: AsyncSession, user: None
    ) -> None:
        from altero.errors import InvalidInputError

        token = (await client.post("/keys/sessions")).json()["sessionToken"]
        api_key = await admin.create_api_key(session, username="octocat", name="Zotero")
        await login.approve_session(session, token, api_key)

        with pytest.raises(InvalidInputError, match="already completed"):
            await login.approve_session(session, token, api_key)

    async def test_an_expired_session_reports_410(
        self, client: httpx.AsyncClient, session: AsyncSession, user: None
    ) -> None:
        # The client tells the user something different for expired than for
        # missing, so the two must not be conflated.
        from datetime import UTC, datetime, timedelta

        from altero.models import LoginSession

        token = (await client.post("/keys/sessions")).json()["sessionToken"]
        stored = await session.get(LoginSession, token)
        assert stored is not None
        stored.created = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            minutes=login.SESSION_LIFETIME_MINUTES + 1
        )
        await session.commit()

        assert (await client.get(f"/keys/sessions/{token}")).status_code == 410

    async def test_pending_sessions_can_be_listed(
        self, client: httpx.AsyncClient, session: AsyncSession, user: None
    ) -> None:
        token = (await client.post("/keys/sessions")).json()["sessionToken"]

        assert [entry.token for entry in await login.list_pending(session)] == [token]


async def test_the_command_line_issues_a_key_that_covers_groups(session: AsyncSession) -> None:
    """Both approval paths grant the same thing.

    The desktop client syncs group libraries as well as the personal one, and a
    key without them presents as a server that has lost them. Asserted through
    the command line's own handler rather than by calling create_api_key with
    the flags, which would only prove that arguments arrive where they are put.
    """
    import argparse

    from altero import cli

    await admin.create_user(session, username="ada")
    started = await login.start_session(session)

    await cli._login_approve(
        session, argparse.Namespace(key=None, username="ada", token=started.token)
    )

    issued = (await admin.list_api_keys(session))[0]
    assert issued.name == login.KEY_NAME
    assert issued.all_groups_read is True
    assert issued.all_groups_write is True
    assert (await login.get_session(session, started.token)).status == login.COMPLETED
