"""Signing in against a directory, over HTTP, with a directory that answers.

The directory is an `httpx.MockTransport` standing in for a real one, so the
whole exchange runs -- discovery, the redirect, the code, the token endpoint,
UserInfo -- and only the socket is fake.

The last class is the one that matters most: whatever federation adds, a
browser session must still be refused by the v3 API, and an API key must still
be the only thing that reaches it.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import ApiKey, AuthRequest, User
from tests.test_web_routes import PASSWORD, csrf_headers, register

ISSUER = "https://sso.example.org"
SUBJECT = "8f14e45f"


class Directory:
    """A stand-in for somebody else's identity provider."""

    def __init__(self) -> None:
        self.claims: dict = {
            "sub": SUBJECT,
            "preferred_username": "grace",
            "name": "Grace Hopper",
            "email": "grace@sso.example.org",
        }
        self.userinfo_claims: dict = {}
        self.nonce = ""
        self.exchanges: list[dict] = []
        self.discovery_calls = 0

    def token_for(self, nonce: str) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": ISSUER,
            "aud": "altero",
            "nonce": nonce,
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "iat": int(now.timestamp()),
            **self.claims,
        }

        def segment(value: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

        return f"{segment({'alg': 'RS256'})}.{segment(payload)}.signature-never-read"

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path

        if path == "/.well-known/openid-configuration":
            self.discovery_calls += 1
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                },
            )

        if path == "/token":
            form = parse_qs(request.content.decode())
            self.exchanges.append({name: value[0] for name, value in form.items()})
            return httpx.Response(
                200,
                json={
                    "access_token": "an-access-token",
                    "token_type": "Bearer",
                    "id_token": self.token_for(self.nonce),
                },
            )

        if path == "/userinfo":
            return httpx.Response(200, json={"sub": SUBJECT, **self.userinfo_claims})

        return httpx.Response(404)


@pytest.fixture
def directory(app: FastAPI) -> Directory:
    """Point the application's outbound client at the stand-in."""
    fake = Directory()
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    return fake


async def add_provider(client: httpx.AsyncClient, **overrides: object) -> httpx.Response:
    body: dict = {
        "slug": "campus",
        "kind": "oidc",
        "displayName": "Campus",
        "issuer": ISSUER,
        "clientId": "altero",
        "clientSecret": "s3cret",
        "createAccounts": True,
        "currentPassword": PASSWORD,
    }
    body.update(overrides)
    return await client.post("/web/admin/providers", json=body, headers=csrf_headers(client))


async def follow(
    client: httpx.AsyncClient, directory: Directory, session: AsyncSession
) -> httpx.Response:
    """Start a sign-in, play the directory's part, and come back."""
    started = await client.get("/web/auth/sso/campus/start")
    parameters = parse_qs(urlparse(started.headers["location"]).query)
    state = parameters["state"][0]
    directory.nonce = parameters["nonce"][0]
    return await client.get(f"/web/auth/sso/campus/callback?code=an-auth-code&state={state}")


class TestConfiguringOne:
    async def test_an_administrator_can_add_one(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)

        response = await add_provider(client)

        assert response.status_code == 201
        assert response.json()["warning"] is None

    async def test_discovery_runs_when_it_is_added(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)

        body = (await add_provider(client)).json()

        assert directory.discovery_calls == 1
        assert body["provider"]["authorizationEndpoint"] == f"{ISSUER}/authorize"

    async def test_the_client_secret_is_never_returned(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        """A signed-in tab must not be a way of reading back a credential the
        instance holds for somebody else's directory."""
        await register(client)

        body = (await add_provider(client)).json()

        assert "s3cret" not in json.dumps(body)
        assert body["provider"]["hasClientSecret"] is True

    async def test_the_callback_to_configure_at_the_directory_is_shown(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        """The single most likely thing to be misconfigured."""
        await register(client)

        body = (await add_provider(client)).json()

        assert body["provider"]["redirectUri"].endswith("/web/auth/sso/campus/callback")

    async def test_an_unreachable_directory_does_not_lose_what_was_typed(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)

        response = await add_provider(client, slug="broken", issuer="https://nowhere.example")

        assert response.status_code == 201
        assert response.json()["warning"] is not None

    async def test_it_takes_the_administrators_own_proof(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)

        response = await client.post(
            "/web/admin/providers",
            json={"slug": "campus", "issuer": ISSUER, "clientId": "altero"},
            headers=csrf_headers(client),
        )

        assert response.status_code == 403

    async def test_an_ordinary_account_cannot_see_them(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        from altero.services import admin, webauth, websessions

        await register(client)
        await add_provider(client)
        plain = await admin.create_user(session, username="grace")
        await webauth.set_password(session, plain, PASSWORD)
        token, _ = await websessions.create(session, plain)
        client.cookies.set("altero_session", token)

        assert (await client.get("/web/admin/providers")).status_code == 403


class TestTheSignInPageIsToldAboutThem:
    async def test_an_enabled_provider_is_offered(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        body = (await client.get("/web/config")).json()

        assert body["providers"] == [{"slug": "campus", "kind": "oidc", "displayName": "Campus"}]

    async def test_nothing_about_how_it_is_configured_is_disclosed(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        """This answers to anybody who loads the page."""
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        body = json.dumps((await client.get("/web/config")).json())

        assert "s3cret" not in body
        assert ISSUER not in body

    async def test_a_disabled_one_is_not_offered(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        await client.patch(
            "/web/admin/providers/campus",
            json={"enabled": False, "currentPassword": PASSWORD},
            headers=csrf_headers(client),
        )

        assert (await client.get("/web/config")).json()["providers"] == []


class TestSigningIn:
    async def test_starting_sends_the_browser_to_the_directory(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        response = await client.get("/web/auth/sso/campus/start")

        assert response.status_code == 303
        assert response.headers["location"].startswith(f"{ISSUER}/authorize?")

    async def test_the_request_is_recorded_so_a_second_worker_could_finish_it(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """In the database rather than in memory, unlike the streaming broker."""
        await register(client)
        await add_provider(client)

        await client.get("/web/auth/sso/campus/start")

        assert await session.scalar(select(AuthRequest)) is not None

    async def test_a_full_sign_in_makes_an_account_and_a_session(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        response = await follow(client, directory, session)

        assert response.status_code == 303
        assert response.headers["location"].endswith("/app/library")
        assert (await client.get("/web/auth/session")).json()["user"]["username"] == "grace"

    async def test_the_code_is_exchanged_with_pkce_and_the_secret(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        await follow(client, directory, session)

        exchange = directory.exchanges[-1]
        assert exchange["grant_type"] == "authorization_code"
        assert exchange["client_secret"] == "s3cret"
        assert exchange["code_verifier"]

    async def test_signing_in_twice_lands_on_the_same_account(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()
        await follow(client, directory, session)
        first = (await client.get("/web/auth/session")).json()["user"]["id"]
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        await follow(client, directory, session)

        assert (await client.get("/web/auth/session")).json()["user"]["id"] == first

    async def test_a_claim_only_userinfo_carries_is_seen(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """Directories keep the token small and put the rest there, and the
        required claim is frequently one of them."""
        await register(client)
        await add_provider(client, requiredClaim="groups", requiredValue="zotero")
        directory.userinfo_claims = {"groups": ["zotero"]}
        client.cookies.clear()

        response = await follow(client, directory, session)

        assert response.headers["location"].endswith("/app/library")

    async def test_losing_the_required_claim_refuses_the_sign_in(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client, requiredClaim="groups", requiredValue="zotero")
        directory.userinfo_claims = {"groups": ["alumni"]}
        client.cookies.clear()

        response = await follow(client, directory, session)

        assert "error=not-permitted" in response.headers["location"]
        assert (await client.get("/web/auth/session")).status_code == 401


class TestTheCallbackRefusesWhatItShould:
    async def test_a_state_that_was_never_issued(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        response = await client.get("/web/auth/sso/campus/callback?code=x&state=never-issued-here")

        assert "error=expired" in response.headers["location"]
        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_a_state_used_twice(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """The row is spent as it is read, so a replayed code finds nothing."""
        await register(client)
        await add_provider(client)
        client.cookies.clear()
        started = await client.get("/web/auth/sso/campus/start")
        parameters = parse_qs(urlparse(started.headers["location"]).query)
        state = parameters["state"][0]
        directory.nonce = parameters["nonce"][0]
        await client.get(f"/web/auth/sso/campus/callback?code=a&state={state}")
        await client.post("/web/auth/logout", headers=csrf_headers(client))

        again = await client.get(f"/web/auth/sso/campus/callback?code=a&state={state}")

        assert "error=expired" in again.headers["location"]

    async def test_a_token_answering_a_different_request(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """The nonce is what pins the token to this sign-in."""
        await register(client)
        await add_provider(client)
        client.cookies.clear()
        started = await client.get("/web/auth/sso/campus/start")
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        directory.nonce = "the-nonce-from-somebody-elses-sign-in"

        response = await client.get(f"/web/auth/sso/campus/callback?code=a&state={state}")

        assert "error=refused" in response.headers["location"]
        assert (await client.get("/web/auth/session")).status_code == 401

    async def test_the_directory_refusing(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        response = await client.get("/web/auth/sso/campus/callback?error=access_denied")

        assert "error=refused" in response.headers["location"]

    async def test_an_unknown_provider(self, client: httpx.AsyncClient) -> None:
        await register(client)

        response = await client.get("/web/auth/sso/nowhere/start")

        assert "error=unknown-provider" in response.headers["location"]


class TestAnAccountsOwnConnections:
    async def test_a_signed_in_account_can_attach_one(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """The supported path for an instance that had accounts before a directory."""
        await register(client)
        await add_provider(client, createAccounts=False)

        started = await client.get("/web/auth/sso/campus/start?purpose=link")
        parameters = parse_qs(urlparse(started.headers["location"]).query)
        directory.nonce = parameters["nonce"][0]
        await client.get(f"/web/auth/sso/campus/callback?code=a&state={parameters['state'][0]}")

        body = (await client.get("/web/account/identities")).json()
        assert len(body["identities"]) == 1
        assert body["identities"][0]["provider"] == "campus"

    async def test_linking_asks_the_directory_to_authenticate_again(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)

        started = await client.get("/web/auth/sso/campus/start?purpose=reauth")

        assert parse_qs(urlparse(started.headers["location"]).query)["prompt"] == ["login"]

    async def test_a_stranger_cannot_start_a_link(
        self, client: httpx.AsyncClient, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()

        response = await client.get("/web/auth/sso/campus/start?purpose=link")

        assert "error=not-signed-in" in response.headers["location"]

    async def test_it_can_be_detached(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client, createAccounts=False)
        started = await client.get("/web/auth/sso/campus/start?purpose=link")
        parameters = parse_qs(urlparse(started.headers["location"]).query)
        directory.nonce = parameters["nonce"][0]
        await client.get(f"/web/auth/sso/campus/callback?code=a&state={parameters['state'][0]}")
        identity = (await client.get("/web/account/identities")).json()["identities"][0]

        removed = await client.request(
            "DELETE",
            f"/web/account/identities/{identity['id']}",
            headers=csrf_headers(client),
        )

        assert removed.status_code == 204
        assert (await client.get("/web/account/identities")).json()["identities"] == []


class TestTheV3ApiIsStillUntouched:
    """Whatever federation adds, a cookie must not reach the sync protocol."""

    async def test_a_federated_session_does_not_authenticate_a_v3_request(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        await register(client)
        await add_provider(client)
        client.cookies.clear()
        await follow(client, directory, session)
        user = await session.scalar(select(User).where(User.username == "grace"))
        assert user is not None

        response = await client.get(f"/users/{user.id}/items")

        assert response.status_code in (401, 403)

    async def test_no_api_key_is_issued_by_signing_in(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """A desktop client still gets its key the way it always did, from a
        signed-in browser -- federation does not hand one out."""
        await register(client)
        await add_provider(client)
        client.cookies.clear()
        await follow(client, directory, session)

        assert list(await session.scalars(select(ApiKey))) == []

    async def test_the_callback_does_not_take_a_csrf_token(
        self, client: httpx.AsyncClient, session: AsyncSession, directory: Directory
    ) -> None:
        """It arrives by navigation from the directory, so there is no header to
        send; the state row is what makes it genuine."""
        await register(client)
        await add_provider(client)
        client.cookies.clear()
        client.cookies.clear()

        response = await follow(client, directory, session)

        assert response.status_code == 303
