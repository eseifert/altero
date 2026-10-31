"""SAML interoperability with a second real IdP and its own XML signer.

The fixture uses SimpleSAMLphp's default response AND assertion signatures.
Set ALTERO_TEST_SIMPLESAMLPHP_URL to the disposable service to run serially.
"""

import base64
import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urljoin

import httpx2
import pytest
from lxml import etree  # ty: ignore[unresolved-import]

from altero.services import saml
from tests.idp.http import ALTERO_URL, Form, live_browser, new_browser
from tests.test_saml import OTHER_CERTIFICATE
from tests.test_web_routes import PASSWORD, csrf_headers

SLUG = "simplesamlphp"
ACS = f"{ALTERO_URL}/web/auth/saml/{SLUG}/acs"
ENTITY = "urn:altero:test:simplesamlphp"


@pytest.fixture
async def simplesamlphp() -> str:
    configured = os.environ.get("ALTERO_TEST_SIMPLESAMLPHP_URL")
    if not configured:
        pytest.skip("set ALTERO_TEST_SIMPLESAMLPHP_URL to run the second real SAML IdP")
    base = configured.rstrip("/")
    async with httpx2.AsyncClient(timeout=15) as client:
        health = await client.get(f"{base}/health.php")
    assert health.status_code == 200
    # Check the actual runtime and PHP's follow-up mitigation, not just a tag.
    assert health.json() == {
        "phpVersion": "8.4.27",
        "simplesamlphpVersion": "2.5.3.1",
        "sessionUploadProgressEnabled": False,
    }
    return base


@pytest.fixture
async def browser(simplesamlphp: str, tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    async with live_browser(tmp_path) as client:
        yield client


async def configure(browser: httpx2.AsyncClient, base: str, **overrides: object) -> None:
    metadata = await browser.get(f"{base}/saml2/idp/metadata.php", follow_redirects=True)
    assert metadata.status_code == 200
    document = etree.fromstring(metadata.content)
    assert document.get("entityID") == ENTITY
    ns = {
        "md": "urn:oasis:names:tc:SAML:2.0:metadata",
        "ds": "http://www.w3.org/2000/09/xmldsig#",
    }
    certificates = document.xpath(
        "./md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']//ds:X509Certificate/text()",
        namespaces=ns,
    )
    endpoints = document.xpath(
        "./md:IDPSSODescriptor/md:SingleSignOnService"
        "[@Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect']/@Location",
        namespaces=ns,
    )
    assert certificates
    assert len(endpoints) == 1
    assert endpoints[0].startswith(f"{base}/")
    provider = {
        "slug": SLUG,
        "kind": "saml",
        "displayName": "SimpleSAMLphp",
        "idpEntityId": ENTITY,
        "ssoUrl": endpoints[0],
        "certificates": "\n".join(
            f"-----BEGIN CERTIFICATE-----\n{value.strip()}\n-----END CERTIFICATE-----"
            for value in certificates
        ),
        "createAccounts": True,
        "currentPassword": PASSWORD,
    }
    provider.update(overrides)
    created = await browser.post(
        "/web/admin/providers", json=provider, headers=csrf_headers(browser)
    )
    assert created.status_code == 201


async def answer(browser: httpx2.AsyncClient, base: str, **parameters: str) -> httpx2.Request:
    started = await browser.get(f"/web/auth/sso/{SLUG}/start", params=parameters)
    assert started.status_code == 303
    assert started.headers["location"].startswith(f"{base}/")
    page = await browser.get(started.headers["location"], follow_redirects=True)
    assert page.status_code == 200
    login = Form(page.text, identifier="f")
    action = urljoin(str(page.url), login.action)
    assert action.startswith(f"{base}/")
    posted = await browser.post(
        action,
        data={**login.fields, "username": "grace", "password": "simplesaml-test-password"},
        follow_redirects=True,
    )
    assert posted.status_code == 200
    assertion = Form(posted.text)
    assert assertion.action == ACS
    encoded = assertion.fields["SAMLResponse"]
    document = etree.fromstring(base64.b64decode(encoded))
    assert document.find("./ds:Signature", saml.NS) is not None
    assert document.find("./saml:Assertion/ds:Signature", saml.NS) is not None
    name = document.find("./saml:Assertion/saml:Subject/saml:NameID", saml.NS)
    assert name is not None
    assert name.get("Format") == "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"
    # SameSite=Lax omits existing cookies on the cross-site assertion POST.
    return httpx2.Request("POST", ACS, data=assertion.fields)


async def sign_in(browser: httpx2.AsyncClient, base: str, **parameters: str) -> httpx2.Response:
    response = await browser.send(await answer(browser, base, **parameters))
    if response.headers.get("location", "").startswith(
        f"{ALTERO_URL}/web/auth/saml/{SLUG}/complete?"
    ):
        return await browser.get(response.headers["location"])
    return response


def refused(response: httpx2.Response, reason: str = "refused") -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"{ALTERO_URL}/app/sign-in?error={reason}"


async def test_two_signed_layers_return_to_the_same_account(
    browser: httpx2.AsyncClient, simplesamlphp: str
) -> None:
    await configure(browser, simplesamlphp, requiredClaim="groups", requiredValue="staff")
    ids = []
    for _ in range(2):
        browser.cookies.clear()
        response = await sign_in(browser, simplesamlphp)
        assert response.headers["location"] == f"{ALTERO_URL}/app/library"
        current = await browser.get("/web/auth/session")
        assert current.status_code == 200
        user = current.json()["user"]
        assert user["username"] == "grace"
        assert user["displayName"] == "Grace Hopper"
        assert user["email"] == "grace@example.org"
        ids.append(user["id"])
        assert (await browser.get("/web/libraries")).status_code == 200
        assert (await browser.get(f"/users/{user['id']}/items")).status_code == 403
    assert ids[0] == ids[1]


@pytest.mark.parametrize("policy", ["provisioning-off", "missing-group"])
async def test_refused_provisioning_creates_no_account(
    browser: httpx2.AsyncClient, simplesamlphp: str, policy: str
) -> None:
    settings = (
        {"createAccounts": False}
        if policy == "provisioning-off"
        else {
            "requiredClaim": "groups",
            "requiredValue": "missing",
        }
    )
    await configure(browser, simplesamlphp, **settings)
    async with new_browser() as visitor:
        refused(await sign_in(visitor, simplesamlphp), "not-permitted")
        assert (await visitor.get("/web/auth/session")).status_code == 401
    accounts = (await browser.get("/web/admin/users")).json()["users"]
    assert [user["username"] for user in accounts] == ["ada"]


async def test_link_and_force_authentication_complete_with_the_existing_session(
    browser: httpx2.AsyncClient, simplesamlphp: str
) -> None:
    await configure(browser, simplesamlphp, createAccounts=False)
    user_id = (await browser.get("/web/auth/session")).json()["user"]["id"]
    linked = await sign_in(browser, simplesamlphp, purpose="link", next="/settings/security")
    assert linked.headers["location"] == f"{ALTERO_URL}/app/settings/security"
    identities = (await browser.get("/web/account/identities")).json()["identities"]
    assert len(identities) == 1
    assert identities[0]["provider"] == SLUG
    browser.cookies.clear()
    assert (await sign_in(browser, simplesamlphp)).headers["location"].endswith("/app/library")
    assert (await browser.get("/web/auth/session")).json()["user"]["id"] == user_id
    before = await browser.post(
        "/web/account/keys", json={"name": "desktop"}, headers=csrf_headers(browser)
    )
    assert before.status_code == 403
    # Retain the IdP session: ForceAuthn must still return its password form.
    proved = await sign_in(browser, simplesamlphp, purpose="reauth")
    assert proved.headers["location"].endswith("/app/library")
    created = await browser.post(
        "/web/account/keys", json={"name": "desktop"}, headers=csrf_headers(browser)
    )
    assert created.status_code == 201


async def test_a_real_response_cannot_be_replayed_after_logout(
    browser: httpx2.AsyncClient, simplesamlphp: str
) -> None:
    await configure(browser, simplesamlphp)
    browser.cookies.clear()
    callback = await answer(browser, simplesamlphp)
    assert (await browser.send(callback)).headers["location"].endswith("/app/library")
    assert (
        await browser.post("/web/auth/logout", headers=csrf_headers(browser))
    ).status_code == 204
    refused(await browser.send(callback), "expired")
    assert (await browser.get("/web/auth/session")).status_code == 401


async def test_altering_signed_claims_does_not_create_a_session(
    browser: httpx2.AsyncClient, simplesamlphp: str
) -> None:
    await configure(browser, simplesamlphp)
    async with new_browser() as visitor:
        callback = await answer(visitor, simplesamlphp)
        fields = parse_qs(callback.content.decode())
        raw = base64.b64decode(fields["SAMLResponse"][0])
        assert b"grace@example.org" in raw
        altered = raw.replace(b"grace@example.org", b"forged@example.org")
        refused(await visitor.post(ACS, data={"SAMLResponse": base64.b64encode(altered).decode()}))
        assert (await visitor.get("/web/auth/session")).status_code == 401


@pytest.mark.parametrize("mismatch", ["certificate", "issuer"])
async def test_a_valid_response_requires_the_configured_trust(
    browser: httpx2.AsyncClient, simplesamlphp: str, mismatch: str
) -> None:
    settings = (
        {"certificates": OTHER_CERTIFICATE}
        if mismatch == "certificate"
        else {
            "idpEntityId": "urn:altero:test:different-idp",
        }
    )
    await configure(browser, simplesamlphp, **settings)
    async with new_browser() as visitor:
        refused(await sign_in(visitor, simplesamlphp))
        assert (await visitor.get("/web/auth/session")).status_code == 401
