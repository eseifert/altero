"""Real OIDC and signed SAML exchanges, with no substituted HTTP transport.

Start tests/idp/compose.yml and set ALTERO_TEST_KEYCLOAK_URL to its base URL.
The imported clients register a loopback altero at port 18765; run serially.
This exercises HTTP forms, not browser JavaScript or SameSite enforcement.
"""

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx2
import pytest
import uvicorn
from lxml import etree  # ty: ignore[unresolved-import]

from altero.app import create_app
from altero.settings import Settings
from tests.test_web_routes import PASSWORD, csrf_headers, register

ALTERO_URL = "http://127.0.0.1:18765"
# Keycloak's SecureContextResolver emits Secure cookies on HTTP loopback except
# for Safari. Python's cookie jar does not implement browsers' loopback exception;
# use that supported server path instead of modifying cookies or their policy.
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)


class Form(HTMLParser):
    """Read an actual IdP form, including HTML-escaped action parameters."""

    def __init__(self, document: str, *, identifier: str) -> None:
        super().__init__(convert_charrefs=True)
        self.identifier = identifier
        self.action = ""
        self.fields: dict[str, str] = {}
        self.inside = False
        self.feed(document)
        assert self.action, f"Keycloak did not return the {identifier} form"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.inside = self.identifier in (attributes.get("id"), attributes.get("name"))
            if self.inside:
                assert (attributes.get("method") or "").lower() == "post"
                self.action = attributes.get("action") or ""
        if self.inside and tag == "input" and attributes.get("name"):
            self.fields[str(attributes["name"])] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.inside = False


@pytest.fixture
async def keycloak() -> str:
    configured = os.environ.get("ALTERO_TEST_KEYCLOAK_URL")
    if not configured:
        pytest.skip("set ALTERO_TEST_KEYCLOAK_URL to run real identity-provider tests")
    realm = f"{configured.rstrip('/')}/realms/altero"
    # A configured but unreachable/misconfigured directory must fail, not skip.
    async with httpx2.AsyncClient(timeout=15) as client:
        response = await client.get(f"{realm}/.well-known/openid-configuration")
    assert response.status_code == 200
    assert response.json()["issuer"] == realm
    return realm


@pytest.fixture
async def browser(keycloak: str, tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'identity.sqlite'}",
        storage_path=tmp_path / "storage",
        public_url=ALTERO_URL,
    )
    app = create_app(settings)
    await app.state.database.create_all()
    running = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
    )
    with closing(socket.socket()) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 18765))
        task = asyncio.create_task(running.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not running.started:
                    if task.done():
                        task.result()
                        raise RuntimeError("altero stopped before accepting requests")
                    await asyncio.sleep(0.01)
            async with httpx2.AsyncClient(
                base_url=ALTERO_URL, timeout=20, headers={"User-Agent": HTTP_USER_AGENT}
            ) as client:
                assert (await register(client)).status_code == 201
                yield client
        finally:
            running.should_exit = True
            await asyncio.wait_for(task, timeout=15)


async def configure(browser: httpx2.AsyncClient, realm: str, kind: str) -> None:
    provider = {
        "slug": kind,
        "kind": kind,
        "displayName": f"Keycloak {kind.upper()}",
        "createAccounts": True,
        "currentPassword": PASSWORD,
    }
    if kind == "oidc":
        provider.update(
            issuer=realm, clientId="altero-oidc", clientSecret="altero-test-client-secret"
        )
    else:
        metadata = await browser.get(f"{realm}/protocol/saml/descriptor")
        assert metadata.status_code == 200
        document = etree.fromstring(metadata.content)
        namespaces = {
            "md": "urn:oasis:names:tc:SAML:2.0:metadata",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }
        certificates = document.xpath(
            "./md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']//ds:X509Certificate/text()",
            namespaces=namespaces,
        )
        assert certificates, "Keycloak metadata carries no signing certificate"
        provider.update(
            idpEntityId=document.get("entityID"),
            ssoUrl=f"{realm}/protocol/saml",
            certificates="\n".join(
                f"-----BEGIN CERTIFICATE-----\n{certificate.strip()}\n-----END CERTIFICATE-----"
                for certificate in certificates
            ),
        )
    response = await browser.post(
        "/web/admin/providers", json=provider, headers=csrf_headers(browser)
    )
    assert response.status_code == 201
    assert response.json()["warning"] is None


async def sign_in(browser: httpx2.AsyncClient, realm: str, kind: str) -> httpx2.Response:
    """Submit Keycloak's password form, stopping at altero's final redirect."""
    started = await browser.get(f"/web/auth/sso/{kind}/start")
    assert started.status_code == 303
    assert started.headers["location"].startswith(f"{realm}/protocol/")
    page = await browser.get(started.headers["location"])
    assert page.status_code == 200
    login = Form(page.text, identifier="kc-form-login")
    action = urljoin(str(page.url), login.action)
    assert action.startswith(f"{realm}/login-actions/")
    response = await browser.post(
        action,
        data={**login.fields, "username": "grace", "password": "keycloak-test-password"},
    )
    if kind == "oidc":
        assert response.status_code == 302
        callback = response.headers["location"]
        assert callback.startswith(f"{ALTERO_URL}/web/auth/sso/oidc/callback?")
        return await browser.get(callback)
    assert response.status_code == 200
    assertion = Form(response.text, identifier="saml-post-binding")
    assert assertion.action == f"{ALTERO_URL}/web/auth/saml/saml/acs"
    assert assertion.fields.get("SAMLResponse")
    # A cross-site POST does not send SameSite=Lax session cookies. Preserve
    # Keycloak's fields, but discard cookies before this unauthenticated ACS.
    browser.cookies.clear()
    return await browser.post(assertion.action, data=assertion.fields)


@pytest.mark.parametrize("kind", ["oidc", "saml"])
async def test_sign_in_and_return_to_the_same_account(
    browser: httpx2.AsyncClient, keycloak: str, kind: str
) -> None:
    await configure(browser, keycloak, kind)
    user_ids = []
    for _ in range(2):
        # Also drops Keycloak's session, so both passes must use its login form.
        browser.cookies.clear()
        assert (await browser.get("/web/auth/session")).status_code == 401
        response = await sign_in(browser, keycloak, kind)
        assert response.status_code == 303
        assert response.headers["location"] == f"{ALTERO_URL}/app/library"
        signed_in = await browser.get("/web/auth/session")
        assert signed_in.status_code == 200
        user = signed_in.json()["user"]
        assert user["username"] == "grace"
        assert user["email"] == "grace@example.org"
        user_ids.append(user["id"])
        identities = (await browser.get("/web/account/identities")).json()["identities"]
        assert len(identities) == 1
        assert identities[0]["provider"] == kind
        assert (await browser.get("/web/libraries")).status_code == 200
        # SSO creates a browser session, never a credential for desktop sync.
        assert (await browser.get(f"/users/{user['id']}/items")).status_code == 403
        logged_out = await browser.post("/web/auth/logout", headers=csrf_headers(browser))
        assert logged_out.status_code == 204
        assert (await browser.get("/web/auth/session")).status_code == 401
    assert user_ids[0] == user_ids[1]
