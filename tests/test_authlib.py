"""An independent OpenID/OAuth client talks to altero over real HTTP.

Authlib generates PKCE/state/nonce, exchanges and refreshes tokens, authenticates
the client, verifies ID tokens and constructs logout requests.
Its stock HTTP integration uses httpx2. No HTTP transport is substituted.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from authlib.integrations.base_client import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.starlette_client.apps import StarletteOAuth2App

from altero.db import Database
from altero.services import oauthclients
from altero.settings import Settings
from tests.idp.http import ALTERO_URL, live_browser
from tests.test_web_routes import csrf_headers

CLIENT_ID = "authlib+notebook"
CALLBACK = "http://127.0.0.1:19874/callback"
SIGNED_OUT = "http://127.0.0.1:19874/signed-out"
SCOPE = "openid profile email library.read"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


@pytest.fixture
async def browser(tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    async with live_browser(tmp_path) as client:
        yield client


@dataclass
class RelyingParty:
    app: StarletteOAuth2App
    metadata: dict[str, Any]
    method: str
    secret: str | None

    def client(self, token: dict | None = None) -> AsyncOAuth2Client:
        client = AsyncOAuth2Client(
            CLIENT_ID,
            self.secret,
            token_endpoint_auth_method=self.method,
            revocation_endpoint_auth_method=self.method,
            token=token,
            scope=SCOPE,
            redirect_uri=CALLBACK,
            timeout=20,
        )
        assert isinstance(client, httpx2.AsyncClient)
        return client


@pytest.fixture(params=["none", "client_secret_basic", "client_secret_post"])
async def relying_party(
    browser: httpx2.AsyncClient, tmp_path: Path, request: pytest.FixtureRequest
) -> RelyingParty:
    method = request.param
    # Client registration is an operator action, through the same service as
    # the CLI. Everything after setup crosses the live HTTP boundary.
    database = Database(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'identity.sqlite'}")
    )
    try:
        async with database.session_factory() as session:
            _, secret = await oauthclients.create(
                session,
                client_id=CLIENT_ID,
                name="Authlib notebook",
                redirect_uris=[CALLBACK],
                post_logout_redirect_uris=[SIGNED_OUT],
                scopes=SCOPE,
                confidential=method != "none",
            )
    finally:
        await database.dispose()
    app = OAuth().register(
        "altero",
        client_id=CLIENT_ID,
        client_secret=secret,
        server_metadata_url=f"{ALTERO_URL}/.well-known/openid-configuration",
        client_kwargs={
            "scope": SCOPE,
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": method,
            "timeout": 20,
        },
    )
    assert isinstance(app, StarletteOAuth2App)
    assert issubclass(app.client_cls, httpx2.AsyncClient)
    metadata = await app.load_server_metadata()
    assert metadata["issuer"] == ALTERO_URL
    assert method in metadata["token_endpoint_auth_methods_supported"]
    assert method in metadata["revocation_endpoint_auth_methods_supported"]
    return RelyingParty(app, metadata, method, secret)


async def authorize(browser: httpx2.AsyncClient, rp: RelyingParty) -> tuple[dict, str]:
    authorization = await rp.app.create_authorization_url(CALLBACK)
    parameters = parse_qs(urlsplit(authorization["url"]).query)
    assert parameters["code_challenge_method"] == ["S256"]
    assert parameters["nonce"] == [authorization["nonce"]]
    started = await browser.get(authorization["url"])
    assert started.status_code == 303
    handle = parse_qs(urlsplit(started.headers["location"]).query)["request"][0]
    pending = await browser.get(f"/web/oauth/pending/{handle}")
    assert pending.status_code == 200
    assert pending.json()["clientId"] == CLIENT_ID
    decided = await browser.post(
        f"/web/oauth/pending/{handle}", json={"approve": True}, headers=csrf_headers(browser)
    )
    assert decided.status_code == 200
    return authorization, decided.json()["redirect"]


async def exchange(rp: RelyingParty, authorization: dict, callback: str, **overrides: str) -> dict:
    parameters = {
        "authorization_response": callback,
        "state": authorization["state"],
        "code_verifier": authorization["code_verifier"],
    }
    parameters.update(overrides)
    return await rp.app.fetch_access_token(CALLBACK, **parameters)


async def tokens(browser: httpx2.AsyncClient, rp: RelyingParty) -> dict:
    authorization, callback = await authorize(browser, rp)
    token = await exchange(rp, authorization, callback)
    # Stock Authlib fetches the discovered JWKS and verifies signature, issuer,
    # audience, nonce, timestamps and at_hash without importing altero's signer.
    claims = await rp.app.parse_id_token(
        token,
        nonce=authorization["nonce"],
        leeway=0,
        claims_options={
            "iss": {"essential": True, "value": ALTERO_URL},
            "aud": {"essential": True, "value": CLIENT_ID},
        },
    )
    assert claims["sub"] == str((await browser.get("/web/auth/session")).json()["user"]["id"])
    assert claims["preferred_username"] == "ada"
    assert claims["email"] == "ada@example.org"
    return token


async def test_discovery_signed_identity_userinfo_and_api_scope(
    browser: httpx2.AsyncClient, relying_party: RelyingParty
) -> None:
    rp = relying_party
    token = await tokens(browser, rp)
    userinfo = await rp.app.userinfo(token=token)
    assert userinfo["preferred_username"] == "ada"
    assert userinfo["email_verified"] is False
    async with rp.client(token) as client:
        items = await client.get(f"{ALTERO_URL}/users/{userinfo['sub']}/items")
        assert items.status_code == 200
        assert items.json() == []
        assert (await client.get(f"{ALTERO_URL}/web/auth/session")).status_code == 401
    assert (await browser.get(f"/users/{userinfo['sub']}/items")).status_code == 403


@pytest.mark.parametrize("failure", ["verifier", "code-replay"])
async def test_code_exchange_refuses_bad_proof_or_a_reused_code(
    browser: httpx2.AsyncClient, relying_party: RelyingParty, failure: str
) -> None:
    rp = relying_party
    authorization, callback = await authorize(browser, rp)
    if failure == "code-replay":
        await exchange(rp, authorization, callback)
    overrides = {"code_verifier": "different-verifier-" * 4} if failure == "verifier" else {}
    with pytest.raises(OAuthError) as refused:
        await exchange(rp, authorization, callback, **overrides)
    assert refused.value.error == "invalid_grant"


async def test_refresh_rotation_and_replay_revoke_the_new_family(
    browser: httpx2.AsyncClient, relying_party: RelyingParty
) -> None:
    rp = relying_party
    original = await tokens(browser, rp)
    async with rp.client(original) as client:
        rotated = await client.refresh_token(rp.metadata["token_endpoint"])
        assert rotated["access_token"] != original["access_token"]
        assert rotated["refresh_token"] != original["refresh_token"]
        assert (await client.get(rp.metadata["userinfo_endpoint"])).status_code == 200
        with pytest.raises(OAuthError) as replayed:
            await client.refresh_token(
                rp.metadata["token_endpoint"], refresh_token=original["refresh_token"]
            )
        assert replayed.value.error == "invalid_grant"
        assert (await client.get(rp.metadata["userinfo_endpoint"])).status_code == 403
        with pytest.raises(OAuthError) as burned:
            await client.refresh_token(
                rp.metadata["token_endpoint"], refresh_token=rotated["refresh_token"]
            )
        assert burned.value.error == "invalid_grant"


@pytest.mark.parametrize("kind", ["access_token", "refresh_token"])
async def test_revocation_has_the_advertised_token_or_family_scope(
    browser: httpx2.AsyncClient, relying_party: RelyingParty, kind: str
) -> None:
    rp = relying_party
    token = await tokens(browser, rp)
    async with rp.client(token) as client:
        revoked = await client.revoke_token(
            rp.metadata["revocation_endpoint"], token=token[kind], token_type_hint=kind
        )
        assert revoked.status_code == 200
        assert (await client.get(rp.metadata["userinfo_endpoint"])).status_code == 403
        if kind == "access_token":
            await client.refresh_token(rp.metadata["token_endpoint"])
            assert (await client.get(rp.metadata["userinfo_endpoint"])).status_code == 200
        else:
            with pytest.raises(OAuthError) as refused:
                await client.refresh_token(rp.metadata["token_endpoint"])
            assert refused.value.error == "invalid_grant"


async def test_device_authorization_uses_browser_consent_and_authlib_token_exchange(
    browser: httpx2.AsyncClient, relying_party: RelyingParty
) -> None:
    rp = relying_party
    async with rp.client() as client:
        response = await client.request(
            "POST",
            rp.metadata["device_authorization_endpoint"],
            data={"client_id": CLIENT_ID, "scope": SCOPE},
            withhold_token=True,
        )
        assert response.status_code == 200
        device = response.json()
        with pytest.raises(OAuthError) as waiting:
            await client.fetch_token(
                rp.metadata["token_endpoint"],
                grant_type=DEVICE_GRANT,
                device_code=device["device_code"],
            )
        assert waiting.value.error == "authorization_pending"
        claimed = await browser.post(
            "/web/oauth/device",
            json={"userCode": device["user_code"]},
            headers=csrf_headers(browser),
        )
        assert claimed.status_code == 200
        handle = claimed.json()["handle"]
        decided = await browser.post(
            f"/web/oauth/pending/{handle}", json={"approve": True}, headers=csrf_headers(browser)
        )
        assert decided.status_code == 200
        assert decided.json()["redirect"] == "/app/device/done"
        await asyncio.sleep(device["interval"])
        token = await client.fetch_token(
            rp.metadata["token_endpoint"],
            grant_type=DEVICE_GRANT,
            device_code=device["device_code"],
        )
        claims = await rp.app.parse_id_token(token, nonce=None, leeway=0)
        assert claims["preferred_username"] == "ada"
        assert (await client.get(rp.metadata["userinfo_endpoint"])).status_code == 200


async def test_authlib_logout_ends_the_browser_session_and_retains_the_grant(
    browser: httpx2.AsyncClient, relying_party: RelyingParty
) -> None:
    rp = relying_party
    token = await tokens(browser, rp)
    logout = await rp.app.create_logout_url(
        post_logout_redirect_uri=SIGNED_OUT, id_token_hint=token["id_token"]
    )
    response = await browser.get(logout["url"])
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target._replace(query="").geturl() == SIGNED_OUT
    assert parse_qs(target.query)["state"] == [logout["state"]]
    assert (await browser.get("/web/auth/session")).status_code == 401
    async with rp.client(token) as client:
        assert (await client.get(rp.metadata["userinfo_endpoint"])).status_code == 200
