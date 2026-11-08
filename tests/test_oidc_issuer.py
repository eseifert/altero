"""An issuer is an identity string, including its trailing slash."""

from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from altero.errors import ForbiddenError, InvalidInputError
from altero.services import identityproviders, oidc
from tests.test_oidc import NONCE, claims, provider
from tests.test_web_identity import ISSUER, Directory, add_provider, follow
from tests.test_web_identity import settings as settings
from tests.test_web_routes import csrf_headers, register

ISSUERS = [ISSUER, f"{ISSUER}/", f"{ISSUER}/application/o/altero/"]


@pytest.mark.parametrize("issuer", ISSUERS)
async def test_configuration_preserves_the_exact_issuer(
    session: AsyncSession,
    issuer: str,
) -> None:
    configured = await identityproviders.create(
        session,
        slug="campus",
        kind="oidc",
        issuer=f" {issuer} ",
        client_id="altero",
    )
    assert configured.issuer == issuer
    await session.refresh(configured)
    assert configured.issuer == issuer


async def test_adding_a_trailing_slash_invalidates_discovery(session: AsyncSession) -> None:
    configured = await identityproviders.create(session, slug="campus", kind="oidc", issuer=ISSUER)
    configured.discovered = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await identityproviders.update(session, configured, {"issuer": f"{ISSUER}/"})
    assert configured.issuer == f"{ISSUER}/"
    assert configured.discovered is None


@pytest.mark.parametrize("issuer", ISSUERS)
async def test_discovery_removes_the_slash_only_when_forming_its_url(issuer: str) -> None:
    def directory(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        return httpx2.Response(
            200,
            json={
                "issuer": issuer,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(directory)) as client:
        discovered = await oidc.Client(client).discover(issuer)
    assert discovered.issuer == issuer


@pytest.mark.parametrize(
    ("configured", "advertised"), [(ISSUER, f"{ISSUER}/"), (f"{ISSUER}/", ISSUER)]
)
async def test_a_slash_mismatch_is_refused_during_discovery(
    configured: str, advertised: str
) -> None:
    def directory(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "issuer": advertised,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(directory)) as client:
        with pytest.raises(InvalidInputError, match="claims to be for"):
            await oidc.Client(client).discover(configured)


@pytest.mark.parametrize(
    ("configured", "asserted"), [(ISSUER, f"{ISSUER}/"), (f"{ISSUER}/", ISSUER)]
)
def test_a_slash_mismatch_remains_refused_in_tokens(configured: str, asserted: str) -> None:
    with pytest.raises(ForbiddenError, match="different identity provider"):
        oidc.validate_claims(claims(iss=asserted), provider(issuer=configured), nonce=NONCE)


@pytest.mark.parametrize("issuer", ISSUERS[1:])
async def test_the_browser_routes_can_sign_in_with_a_slash_issuer(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    issuer: str,
) -> None:
    directory = Directory()
    directory.claims["iss"] = issuer

    def answer(request: httpx2.Request) -> httpx2.Response:
        if urlparse(str(request.url)).path.endswith("/.well-known/openid-configuration"):
            response = directory.handle(
                httpx2.Request("GET", f"{ISSUER}/.well-known/openid-configuration")
            )
            return httpx2.Response(200, json={**response.json(), "issuer": issuer})
        return directory.handle(request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(answer)) as outbound:
        app.state.http_client = outbound
        assert (await register(client)).status_code == 201
        added = await add_provider(client, issuer=issuer)
        assert added.json()["provider"]["issuer"] == issuer
        assert added.json()["warning"] is None
        client.cookies.clear()
        completed = await follow(client, directory, session)
        assert completed.status_code == 303
        assert completed.headers["location"].endswith("/app/library")
        signed_in = await client.get("/web/auth/session")
        assert signed_in.json()["user"]["username"] == "grace"
        assert (await client.get("/web/libraries")).status_code == 200
        assert (await client.get("/users/2/items")).status_code in (401, 403)
        assert (
            await client.post("/web/auth/logout", headers=csrf_headers(client))
        ).status_code == 204
