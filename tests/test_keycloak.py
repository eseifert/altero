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


async def configure(
    browser: httpx2.AsyncClient, realm: str, kind: str, **overrides: object
) -> None:
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
    provider.update(overrides)
    response = await browser.post(
        "/web/admin/providers", json=provider, headers=csrf_headers(browser)
    )
    assert response.status_code == 201
    assert response.json()["warning"] is None


async def answer(
    browser: httpx2.AsyncClient, realm: str, kind: str, **parameters: str
) -> httpx2.Request:
    """Obtain Keycloak's real answer without yet submitting it to altero."""
    started = await browser.get(f"/web/auth/sso/{kind}/start", params=parameters)
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
        return browser.build_request("GET", callback)
    assert response.status_code == 200
    assertion = Form(response.text, identifier="saml-post-binding")
    assert assertion.action == f"{ALTERO_URL}/web/auth/saml/saml/acs"
    assert assertion.fields.get("SAMLResponse")
    # Construct the cross-site POST without the client's SameSite=Lax cookies.
    # Keep its jar: a browser retains those cookies for later same-site requests.
    return httpx2.Request("POST", assertion.action, data=assertion.fields)


async def sign_in(
    browser: httpx2.AsyncClient, realm: str, kind: str, **parameters: str
) -> httpx2.Response:
    response = await browser.send(await answer(browser, realm, kind, **parameters))
    if response.headers.get("location", "").startswith(
        f"{ALTERO_URL}/web/auth/saml/{kind}/complete?"
    ):
        return await browser.get(response.headers["location"])
    return response


@pytest.fixture
async def directory(keycloak: str) -> AsyncIterator[httpx2.AsyncClient]:
    """Control only the disposable realm, using its fixture service account."""
    async with httpx2.AsyncClient(timeout=20) as client:
        token = await client.post(
            f"{keycloak}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "altero-fixtures",
                "client_secret": "altero-test-management-secret",
            },
        )
    assert token.status_code == 200
    base = keycloak.removesuffix("/realms/altero")
    async with httpx2.AsyncClient(
        base_url=f"{base}/admin/realms/altero/",
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=20,
    ) as client:
        yield client


def new_browser() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=ALTERO_URL, timeout=20, headers={"User-Agent": HTTP_USER_AGENT}
    )


def assert_refused(response: httpx2.Response, reason: str = "not-permitted") -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"{ALTERO_URL}/app/sign-in?error={reason}"


@pytest.mark.parametrize("kind", ["oidc", "saml"])
async def test_linking_and_reauthentication_keep_the_existing_account(
    browser: httpx2.AsyncClient, keycloak: str, kind: str
) -> None:
    await configure(browser, keycloak, kind, createAccounts=False)
    before = (await browser.get("/web/auth/session")).json()["user"]
    linked = await sign_in(browser, keycloak, kind, purpose="link", next="/settings/security")
    assert linked.status_code == 303
    assert linked.headers["location"] == f"{ALTERO_URL}/app/settings/security"
    identities = (await browser.get("/web/account/identities")).json()["identities"]
    assert len(identities) == 1
    assert identities[0]["provider"] == kind
    assert (await browser.get("/web/auth/session")).json()["user"]["id"] == before["id"]
    browser.cookies.clear()
    signed_in = await sign_in(browser, keycloak, kind)
    assert signed_in.headers["location"] == f"{ALTERO_URL}/app/library"
    assert (await browser.get("/web/auth/session")).json()["user"]["id"] == before["id"]
    assert (await browser.get("/web/admin/users")).json()["users"][0]["username"] == "ada"
    # An ordinary sign-in has no fresh proof. Reauthentication must establish
    # it on this same session, allowing passwordless API-key issuance.
    refused = await browser.post(
        "/web/account/keys", json={"name": "desktop"}, headers=csrf_headers(browser)
    )
    assert refused.status_code == 403
    for cookie in list(browser.cookies.jar):
        if cookie.path.startswith("/realms/"):
            browser.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    proved = await sign_in(browser, keycloak, kind, purpose="reauth")
    assert proved.headers["location"] == f"{ALTERO_URL}/app/library"
    created = await browser.post(
        "/web/account/keys", json={"name": "desktop"}, headers=csrf_headers(browser)
    )
    assert created.status_code == 201


@pytest.mark.parametrize("kind", ["oidc", "saml"])
async def test_account_creation_can_be_disabled(
    browser: httpx2.AsyncClient, keycloak: str, kind: str
) -> None:
    await configure(browser, keycloak, kind, createAccounts=False)
    async with new_browser() as visitor:
        assert_refused(await sign_in(visitor, keycloak, kind))
        assert (await visitor.get("/web/auth/session")).status_code == 401
    accounts = (await browser.get("/web/admin/users")).json()["users"]
    assert [user["username"] for user in accounts] == ["ada"]


@pytest.mark.parametrize("kind", ["oidc", "saml"])
async def test_a_required_group_refuses_a_new_account(
    browser: httpx2.AsyncClient, keycloak: str, kind: str
) -> None:
    await configure(browser, keycloak, kind, requiredClaim="groups", requiredValue="missing")
    async with new_browser() as visitor:
        assert_refused(await sign_in(visitor, keycloak, kind))
        assert (await visitor.get("/web/auth/session")).status_code == 401
    accounts = (await browser.get("/web/admin/users")).json()["users"]
    assert [user["username"] for user in accounts] == ["ada"]


@pytest.mark.parametrize("kind", ["oidc", "saml"])
@pytest.mark.parametrize("revoke", [False, True])
async def test_losing_a_directory_group_suspends_access_and_optionally_revokes_keys(
    browser: httpx2.AsyncClient,
    directory: httpx2.AsyncClient,
    keycloak: str,
    kind: str,
    revoke: bool,
) -> None:
    await configure(
        browser,
        keycloak,
        kind,
        requiredClaim="groups",
        requiredValue="researchers",
        revokeKeysOnLoss=revoke,
    )
    users = await directory.get("users", params={"username": "grace", "exact": "true"})
    assert users.status_code == 200
    assert len(users.json()) == 1
    directory_user = users.json()[0]["id"]
    groups = await directory.get(f"users/{directory_user}/groups")
    assert groups.status_code == 200
    group = next(group for group in groups.json() if group["name"] == "researchers")
    membership = f"users/{directory_user}/groups/{group['id']}"
    async with new_browser() as member, new_browser() as returning:
        signed_in = await sign_in(member, keycloak, kind)
        assert signed_in.headers["location"] == f"{ALTERO_URL}/app/library"
        user_id = (await member.get("/web/auth/session")).json()["user"]["id"]
        # A local password permits key issuance without conflating this scenario
        # with the separate SSO reauthentication tests.
        password = await browser.post(
            f"/web/admin/users/{user_id}/password",
            json={"password": PASSWORD, "currentPassword": PASSWORD},
            headers=csrf_headers(browser),
        )
        assert password.status_code == 204
        # Setting a password revokes old browser sessions. Establish the live
        # session whose access must stop when the directory group is lost.
        logged_in = await member.post(
            "/web/auth/login", json={"username": "grace", "password": PASSWORD}
        )
        assert logged_in.status_code == 200
        created = await member.post(
            "/web/account/keys",
            json={"name": "desktop", "currentPassword": PASSWORD},
            headers=csrf_headers(member),
        )
        assert created.status_code == 201
        key = {"Zotero-API-Key": created.json()["key"]}
        items_url = f"/users/{user_id}/items"
        assert (await member.get(items_url, headers=key)).status_code == 200
        removed = False
        try:
            assert (await directory.delete(membership)).status_code == 204
            removed = True
            # Group removal alone sends no event to altero; the check is at sign-in.
            assert (await member.get(items_url, headers=key)).status_code == 200
            assert_refused(await sign_in(returning, keycloak, kind))
            assert (await returning.get("/web/auth/session")).status_code == 401
            assert (await member.get("/web/auth/session")).status_code == 401
            assert (await member.get(items_url, headers=key)).status_code == 403
            accounts = (await browser.get("/web/admin/users")).json()["users"]
            account = next(account for account in accounts if account["id"] == user_id)
            assert account["disabled"] is True
            assert account["keys"] == (0 if revoke else 1)
            assert (await directory.put(membership)).status_code == 204
            removed = False
            returning.cookies.clear()
            assert_refused(await sign_in(returning, keycloak, kind))
            restored = await browser.patch(
                f"/web/admin/users/{user_id}",
                json={"disabled": False, "currentPassword": PASSWORD},
                headers=csrf_headers(browser),
            )
            assert restored.status_code == 200
            expected = 403 if revoke else 200
            assert (await member.get(items_url, headers=key)).status_code == expected
        finally:
            if removed:
                assert (await directory.put(membership)).status_code == 204


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
