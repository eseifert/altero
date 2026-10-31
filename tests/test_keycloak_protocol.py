"""Rollover, replay and validity windows using actual Keycloak answers.

Only the validator clock is adjusted for skew tests. HTTP, signed assertions,
token claims and the real directory's key rotation are left intact.
"""

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest
from lxml import etree  # ty: ignore[unresolved-import]

from altero.models import IdentityProvider
from altero.services import oidc, saml
from tests.test_keycloak import (
    ALTERO_URL,
    answer,
    assert_refused,
    configure,
    new_browser,
    sign_in,
)
from tests.test_keycloak import (
    browser as browser,
)
from tests.test_keycloak import (
    directory as directory,
)
from tests.test_keycloak import (
    keycloak as keycloak,
)
from tests.test_web_routes import PASSWORD, csrf_headers


@pytest.mark.parametrize("kind", ["oidc", "saml"])
async def test_a_real_callback_cannot_be_replayed_after_logout(
    browser: httpx2.AsyncClient, keycloak: str, kind: str
) -> None:
    await configure(browser, keycloak, kind)
    async with new_browser() as visitor:
        callback = await answer(visitor, keycloak, kind)
        first = await visitor.send(callback)
        assert first.headers["location"] == f"{ALTERO_URL}/app/library"
        assert (await visitor.get("/web/auth/session")).status_code == 200
        logout = await visitor.post("/web/auth/logout", headers=csrf_headers(visitor))
        assert logout.status_code == 204
        again = await visitor.send(callback)
        assert_refused(again, "expired")
        assert "set-cookie" not in again.headers
        assert (await visitor.get("/web/auth/session")).status_code == 401


@pytest.mark.parametrize("kind", ["oidc", "saml"])
@pytest.mark.parametrize("bound", ["early", "late"])
@pytest.mark.parametrize(("minutes", "accepted"), [(4, True), (6, False)])
async def test_real_assertions_respect_the_five_minute_skew_window(
    browser: httpx2.AsyncClient,
    keycloak: str,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    bound: str,
    minutes: int,
    accepted: bool,
) -> None:
    await configure(browser, keycloak, kind)
    async with new_browser() as visitor:
        callback = await answer(visitor, keycloak, kind)
        delta = timedelta(minutes=minutes)
        if kind == "saml":
            encoded = parse_qs(callback.content.decode())["SAMLResponse"][0]
            document = etree.fromstring(base64.b64decode(encoded))
            conditions = document.find("./saml:Assertion/saml:Conditions", saml.NS)
            assert conditions is not None
            if bound == "early":
                instant = datetime.fromisoformat(conditions.get("NotBefore")) - delta
            else:
                confirmation = document.find(
                    "./saml:Assertion/saml:Subject/saml:SubjectConfirmation/"
                    "saml:SubjectConfirmationData",
                    saml.NS,
                )
                assert confirmation is not None
                expires = min(
                    datetime.fromisoformat(conditions.get("NotOnOrAfter")),
                    datetime.fromisoformat(confirmation.get("NotOnOrAfter")),
                )
                instant = expires + delta
            monkeypatch.setattr(saml, "_now", lambda: instant.replace(tzinfo=None))
        else:
            original = oidc.validate_claims

            def check_at_bound(
                claims: dict[str, Any], provider: IdentityProvider, *, nonce: str
            ) -> None:
                # The real token has not arrived until the live code exchange.
                # Choose its actual iat/exp as the reference without editing it.
                reference = claims["iat" if bound == "early" else "exp"]
                moment = datetime.fromtimestamp(reference, UTC).replace(tzinfo=None)
                original(
                    claims,
                    provider,
                    nonce=nonce,
                    now=moment - delta if bound == "early" else moment + delta,
                )

            monkeypatch.setattr(oidc, "validate_claims", check_at_bound)
        response = await visitor.send(callback)
        if accepted:
            assert response.headers["location"] == f"{ALTERO_URL}/app/library"
            assert (await visitor.get("/web/auth/session")).status_code == 200
        else:
            assert_refused(response, "refused")
            assert (await visitor.get("/web/auth/session")).status_code == 401
            accounts = (await browser.get("/web/admin/users")).json()["users"]
            assert [user["username"] for user in accounts] == ["ada"]


async def active_signing_certificate(directory: httpx2.AsyncClient) -> tuple[str, str]:
    response = await directory.get("keys")
    assert response.status_code == 200
    body = response.json()
    active = body["active"]["RS256"]
    key = next(key for key in body["keys"] if key["kid"] == active)
    return active, f"-----BEGIN CERTIFICATE-----\n{key['certificate']}\n-----END CERTIFICATE-----"


async def trust(browser: httpx2.AsyncClient, certificates: str) -> None:
    changed = await browser.patch(
        "/web/admin/providers/saml",
        json={"certificates": certificates, "currentPassword": PASSWORD},
        headers=csrf_headers(browser),
    )
    assert changed.status_code == 200


async def test_saml_certificate_rollover_accepts_both_keys_and_removes_old_trust(
    browser: httpx2.AsyncClient, directory: httpx2.AsyncClient, keycloak: str
) -> None:
    await configure(browser, keycloak, "saml")
    old_id, old_certificate = await active_signing_certificate(directory)
    await trust(browser, old_certificate)
    async with new_browser() as visitor:
        initial = await sign_in(visitor, keycloak, "saml")
        assert initial.headers["location"] == f"{ALTERO_URL}/app/library"
        account = (await visitor.get("/web/auth/session")).json()["user"]["id"]
        realm = await directory.get("")
        assert realm.status_code == 200
        component = await directory.post(
            "components",
            json={
                "name": "altero-test-rollover",
                "parentId": realm.json()["id"],
                "providerId": "rsa-generated",
                "providerType": "org.keycloak.keys.KeyProvider",
                "config": {
                    "priority": ["200"],
                    "enabled": ["true"],
                    "active": ["true"],
                    "algorithm": ["RS256"],
                    "keySize": ["2048"],
                },
            },
        )
        assert component.status_code == 201
        component_url = component.headers["location"]
        removed = False
        try:
            new_id, new_certificate = await active_signing_certificate(directory)
            assert new_id != old_id
            assert new_certificate != old_certificate
            visitor.cookies.clear()
            assert_refused(await sign_in(visitor, keycloak, "saml"), "refused")
            assert (await visitor.get("/web/auth/session")).status_code == 401
            for certificates in (
                f"{old_certificate}\n{new_certificate}",
                f"{new_certificate}\n{old_certificate}",
            ):
                await trust(browser, certificates)
                visitor.cookies.clear()
                signed_in = await sign_in(visitor, keycloak, "saml")
                assert signed_in.headers["location"] == f"{ALTERO_URL}/app/library"
                assert (await visitor.get("/web/auth/session")).json()["user"]["id"] == account
            assert (await directory.delete(component_url)).status_code == 204
            removed = True
            assert (await active_signing_certificate(directory))[0] == old_id
            visitor.cookies.clear()
            # The previous key still works when it is second in the PEM bundle.
            signed_in = await sign_in(visitor, keycloak, "saml")
            assert signed_in.headers["location"] == f"{ALTERO_URL}/app/library"
            await trust(browser, new_certificate)
            visitor.cookies.clear()
            assert_refused(await sign_in(visitor, keycloak, "saml"), "refused")
            assert (await visitor.get("/web/auth/session")).status_code == 401
        finally:
            if not removed:
                assert (await directory.delete(component_url)).status_code == 204
