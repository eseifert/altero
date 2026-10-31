"""A verified SAML POST hands linking back to a cookie-authenticated GET."""

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from lxml import etree  # ty: ignore[unresolved-import]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from altero.models import AuthRequest, FederatedIdentity, IdentityProvider
from altero.services import websessions
from tests.test_saml import CERTIFICATE, IDP, authn_request, signed
from tests.test_web_identity import add_provider
from tests.test_web_routes import register

BASE = "http://testserver"


async def prepare(
    client: httpx2.AsyncClient, session: AsyncSession, *, purpose: str = "link"
) -> str:
    assert (await register(client)).status_code == 201
    provider = await add_provider(
        client,
        kind="saml",
        idpEntityId=IDP,
        certificates=CERTIFICATE,
        ssoUrl=f"{IDP}/saml",
        createAccounts=False,
    )
    assert provider.status_code == 201
    if purpose == "reauth":
        user_id = (await client.get("/web/auth/session")).json()["user"]["id"]
        session.add(
            FederatedIdentity(
                provider_id=provider.json()["provider"]["id"],
                user_id=user_id,
                subject="grace-subject-id",
                asserted_name="Grace",
            )
        )
        await session.commit()
        record = await websessions.lookup(session, client.cookies.get("altero_session"))
        assert record is not None
        record.reauthenticated = None
        await session.commit()
    started = await client.get(
        "/web/auth/sso/campus/start", params={"purpose": purpose, "next": "/settings/security"}
    )
    document = etree.fromstring(authn_request(started.headers["location"]).encode())
    request_id = document.get("ID")
    assertion = signed(
        issuer=IDP,
        audience=BASE,
        recipient=f"{BASE}/web/auth/saml/campus/acs",
        in_response_to=request_id,
    )
    # An actual cross-site POST has no existing session cookie. The browser
    # retains its jar and can send it on the subsequent top-level GET.
    response = await client.send(
        httpx2.Request("POST", f"{BASE}/web/auth/saml/campus/acs", data={"SAMLResponse": assertion})
    )
    assert response.status_code == 303
    assert "set-cookie" not in response.headers
    location = response.headers["location"]
    assert location.startswith(f"{BASE}/web/auth/saml/campus/complete?state=")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    return location


@pytest.mark.parametrize("purpose", ["link", "reauth"])
async def test_the_original_session_completes_a_verified_handoff(
    client: httpx2.AsyncClient, session: AsyncSession, purpose: str
) -> None:
    location = await prepare(client, session, purpose=purpose)
    pending = await session.scalar(select(AuthRequest))
    assert pending is not None
    assert pending.expires < datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=3)
    before = (await client.get("/web/account/identities")).json()["identities"]
    assert len(before) == (1 if purpose == "reauth" else 0)
    completed = await client.get(location)
    assert completed.headers["location"] == f"{BASE}/app/settings/security"
    assert "set-cookie" not in completed.headers
    assert len((await client.get("/web/account/identities")).json()["identities"]) == 1
    record = await websessions.lookup(session, client.cookies.get("altero_session"))
    assert record is not None
    assert record.reauthenticated is not None
    assert (await client.get(location)).headers["location"].endswith("error=expired")


@pytest.mark.parametrize(
    "failure", ["no-cookie", "other-user", "expired", "disabled", "wrong-provider"]
)
async def test_a_handoff_does_not_grant_authority_by_itself(
    client: httpx2.AsyncClient, session: AsyncSession, failure: str
) -> None:
    location = await prepare(client, session)
    if failure == "no-cookie":
        client.cookies.clear()
    elif failure == "other-user":
        from altero.services import admin

        user = await admin.create_user(session, username="other")
        token, _ = await websessions.create(session, user)
        client.cookies.clear()
        client.cookies.set("altero_session", token)
    elif failure == "expired":
        pending = await session.scalar(select(AuthRequest))
        assert pending is not None
        pending.expires = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await session.commit()
    elif failure == "disabled":
        provider = await session.scalar(select(IdentityProvider))
        assert provider is not None
        provider.enabled = False
        await session.commit()
    else:
        location = location.replace("/campus/", "/other/")
    completed = await client.get(location)
    assert "/app/settings/security" not in completed.headers["location"]
    assert "error=" in completed.headers["location"]
    assert list(await session.scalars(select(FederatedIdentity))) == []


async def test_an_unverified_request_cannot_be_completed(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    location = await prepare(client, session)
    pending = await session.scalar(select(AuthRequest))
    assert pending is not None
    pending.verified_saml = None
    await session.commit()
    response = await client.get(location)
    assert "error=expired" in response.headers["location"]
    assert list(await session.scalars(select(FederatedIdentity))) == []


@pytest.mark.parametrize("callback", ["oidc", "saml"])
async def test_a_verified_handoff_cannot_be_used_as_a_fresh_assertion_request(
    client: httpx2.AsyncClient, session: AsyncSession, callback: str
) -> None:
    await prepare(client, session)
    pending = await session.scalar(select(AuthRequest))
    assert pending is not None
    if callback == "oidc":
        response = await client.get(
            "/web/auth/sso/campus/callback", params={"state": pending.state, "code": "unused"}
        )
    else:
        response = await client.post(
            "/web/auth/saml/campus/acs",
            data={"SAMLResponse": signed(in_response_to=pending.state)},
        )
    assert response.headers["location"].endswith("error=expired")
    assert list(await session.scalars(select(FederatedIdentity))) == []
